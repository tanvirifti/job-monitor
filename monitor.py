#!/usr/bin/env python3
"""
Checks a few job sources, keeps track of what it has already seen, and
sends a message when something new turns up that you could actually apply
for.

Designed to run unattended on GitHub Actions. Nothing here needs a browser
or a database.

    python monitor.py            normal run
    python monitor.py --dry-run  fetch and filter, but send nothing and
                                 do not update the state file
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests

import config
from email_reader import fetch_email_alerts

# ----------------------------------------------------------------- setup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("monitor")

STATE_FILE = Path(__file__).parent / "seen_jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}

def get_with_retry(url, attempts=3, pause=2.0):
    """
    Adzuna returns the occasional 502 or 503. Without a retry those queries
    fail silently and that whole search is skipped for the day, which on one
    run lost three of fourteen searches. Two extra attempts costs a few
    seconds and recovers nearly all of them.

    Only server-side errors and timeouts are retried. A 400 or 401 means the
    request itself is wrong and will not improve by asking again.
    """
    last = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code in (502, 503, 504, 429):
                last = f"{r.status_code} from server"
                if attempt < attempts:
                    time.sleep(pause * attempt)
                    continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as exc:
            last = str(exc)
            if attempt < attempts:
                time.sleep(pause * attempt)
                continue
            raise
    raise requests.exceptions.RequestException(last or "request failed")


ADZUNA_ID = os.environ.get("ADZUNA_APP_ID", "").strip()
ADZUNA_KEY = os.environ.get("ADZUNA_APP_KEY", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


# ----------------------------------------------------------------- state


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        log.warning("state file was unreadable, starting fresh")
        return {}


def save_state(state):
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.FORGET_AFTER_DAYS)
    trimmed = {
        k: v
        for k, v in state.items()
        if datetime.fromisoformat(v).replace(tzinfo=timezone.utc) > cutoff
    }
    dropped = len(state) - len(trimmed)
    STATE_FILE.write_text(json.dumps(trimmed, indent=1, sort_keys=True))
    log.info("state saved: %d remembered%s", len(trimmed),
             f", {dropped} expired" if dropped else "")


def job_id(job):
    """Stable id for a posting, so the same role is not alerted twice."""
    basis = f"{job['company']}|{job['title']}|{job['location']}".lower()
    return re.sub(r"[^a-z0-9|]", "", basis)[:180]


# ----------------------------------------------------------------- filtering


# Some keywords are short enough to appear inside longer, unrelated words.
# "intern" sits inside "internal" and "international", which would let an
# Internal Auditor role through. Matching on word boundaries avoids that
# without needing a separate exception list.
def _contains_phrase(text, phrase):
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text) is not None


def wanted(job):
    title = job["title"].lower()
    loc = job["location"].lower()

    if any(bad in loc for bad in config.EXCLUDE_LOCATIONS):
        return False
    if any(_contains_phrase(title, bad.strip()) for bad in config.EXCLUDE_WORDS):
        return False
    return any(_contains_phrase(title, good.strip()) for good in config.INCLUDE_WORDS)


# ----------------------------------------------------------------- sources


def fetch_adzuna():
    """Adzuna aggregates most UK job boards. This is the workhorse."""
    if not (ADZUNA_ID and ADZUNA_KEY):
        log.warning("Adzuna keys missing, skipping this source")
        return []

    # One set per weekday keeps the monthly call count inside the free tier
    # while covering far more search terms than a single fixed list could.
    today = datetime.now(timezone.utc).weekday()
    rotating = config.ADZUNA_QUERY_SETS.get(today, config.ADZUNA_QUERY_SETS[0])

    # core terms run daily; the rotating set adds breadth without blowing
    # through the monthly call allowance. dict.fromkeys keeps the order and
    # drops any term that appears in both.
    queries = list(dict.fromkeys(config.ADZUNA_DAILY_CORE + rotating))
    log.info("weekday %d: %d core + %d rotating = %d searches",
             today, len(config.ADZUNA_DAILY_CORE), len(rotating), len(queries))

    found = []
    for query in queries:
        where = (
            f"&where={quote_plus(config.ADZUNA_WHERE)}"
            if config.ADZUNA_WHERE.strip()
            else ""  # no where parameter means the whole of GB
        )
        url = (
            "https://api.adzuna.com/v1/api/jobs/gb/search/1"
            f"?app_id={ADZUNA_ID}&app_key={ADZUNA_KEY}"
            f"&results_per_page=50"
            f"&what={quote_plus(query)}"
            f"{where}"
            f"&max_days_old={config.ADZUNA_MAX_DAYS_OLD}"
            "&content-type=application/json"
        )
        try:
            r = get_with_retry(url)
            results = r.json().get("results", [])
        except Exception as exc:
            log.error("Adzuna query %r failed after retries: %s",
                      query, str(exc)[:120])
            continue

        for j in results:
            found.append(
                {
                    "source": "Adzuna",
                    "company": (j.get("company") or {}).get("display_name", "Unknown"),
                    "title": strip_tags(j.get("title", "")),
                    "location": (j.get("location") or {}).get("display_name", ""),
                    "url": j.get("redirect_url", ""),
                    "posted": j.get("created", ""),
                }
            )
        log.info("Adzuna %-34r %3d results", query, len(results))
        time.sleep(0.4)

    return found


def fetch_civil_service():
    """
    Civil Service Jobs carries most of the Tier 1 list: ONS, Cabinet Office,
    DWP, HMRC, DfT, MoJ, Ofcom, Environment Agency, the Met Office.

    It is a CGI application with no API and no stable query string, and the
    first attempt at reading its search page returned nothing at all. Rather
    than keep guessing at markup that can change without notice, this asks
    Adzuna for the same employers by name. Adzuna already indexes them, and
    an aggregator that publishes an API is a far safer dependency than a
    page scrape.

    Costs a few extra API calls, well within the free monthly allowance.
    """
    if not (ADZUNA_ID and ADZUNA_KEY):
        return []

    found = []
    for employer in config.PUBLIC_SECTOR_EMPLOYERS:
        url = (
            "https://api.adzuna.com/v1/api/jobs/gb/search/1"
            f"?app_id={ADZUNA_ID}&app_key={ADZUNA_KEY}"
            f"&results_per_page=25"
            f"&what={quote_plus(employer)}"
            f"&max_days_old={config.ADZUNA_MAX_DAYS_OLD}"
            "&content-type=application/json"
        )
        try:
            r = get_with_retry(url)
            results = r.json().get("results", [])
        except Exception as exc:
            log.error("public sector query %r failed after retries: %s",
                      employer, str(exc)[:120])
            continue

        for j in results:
            found.append(
                {
                    "source": "Public sector",
                    "company": (j.get("company") or {}).get("display_name", "Unknown"),
                    "title": strip_tags(j.get("title", "")),
                    "location": (j.get("location") or {}).get("display_name", ""),
                    "url": j.get("redirect_url", ""),
                    "posted": j.get("created", ""),
                }
            )
        log.info("PublicSector %-30r %3d results", employer, len(results))
        time.sleep(0.4)

    return found


def strip_tags(text):
    return re.sub(r"<[^>]+>", "", text or "").replace("&amp;", "&").strip()


# ----------------------------------------------------------------- alerting


TG_LIMIT = 3900          # Telegram allows 4096; leave room for the header
MAX_MESSAGES = 15        # roughly 250 roles; a first run can be this big


def _post(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    if r.status_code != 200:
        log.error("Telegram refused the message: %s %s", r.status_code, r.text[:300])
        return False
    return True


def send_telegram(jobs):
    """
    Sends the roles, split across as many messages as it takes.

    An earlier version built one message and cut it at 4,000 characters,
    which quietly dropped most of a 153-role batch while still marking all
    of them as seen. Nothing is truncated now: if the list does not fit, it
    goes out as several messages.

    Plain text, not Markdown. Telegram's Markdown parser rejects ordinary
    job titles containing brackets or underscores, which produced a 400 on
    an early run.

    Returns True only if every message went out, so the caller knows whether
    it is safe to record these as seen.
    """
    if not (TG_TOKEN and TG_CHAT):
        log.warning("Telegram not configured, printing instead")
        for j in jobs:
            print(f"  {j['company']} | {j['title']} | {j['location']}\n    {j['url']}")
        return False

    # build one block per role, then pack blocks into messages
    blocks = []
    for j in jobs:
        bits = [b for b in (j["company"], j["location"][:38], j["source"]) if b]
        blocks.append(f"{j['title']}\n{' | '.join(bits)}\n{j['url']}")

    total = len(jobs)
    messages, current = [], ""
    for block in blocks:
        candidate = (current + "\n\n" + block) if current else block
        if len(candidate) > TG_LIMIT:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)

    delivered_count = total
    dropped = 0
    if len(messages) > MAX_MESSAGES:
        delivered_count = sum(m.count("\n\n") + 1 for m in messages[:MAX_MESSAGES])
        dropped = total - delivered_count
        messages = messages[:MAX_MESSAGES]

    ok = True
    for i, body in enumerate(messages, 1):
        header = f"{total} new role{'s' if total != 1 else ''}"
        if len(messages) > 1:
            header += f"  ({i} of {len(messages)})"
        if not _post(header + "\n\n" + body):
            ok = False
            break
        time.sleep(0.6)          # stay under Telegram's rate limit

    if ok and dropped:
        _post(f"{dropped} more were found but not listed. "
              f"Widen EXCLUDE_WORDS or check the Actions log.")
        log.warning("%d roles found but not sent, message cap reached", dropped)

    if ok:
        log.info("sent %d of %d role(s) across %d message(s)",
                 delivered_count, total, len(messages))
    # the caller records only what was actually delivered
    return delivered_count if ok else 0


def escape_md(s):
    return re.sub(r"([*_`\[\]])", r"\\\1", s or "")


# ----------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and filter, but send nothing and save nothing")
    args = ap.parse_args()

    log.info("starting run%s", " (dry run)" if args.dry_run else "")

    raw = []
    raw += fetch_adzuna()
    raw += fetch_civil_service()
    raw += fetch_email_alerts()
    log.info("fetched %d postings across all sources", len(raw))

    relevant = [j for j in raw if wanted(j)]
    log.info("%d passed the filter", len(relevant))

    state = load_state()
    fresh, seen_now = [], {}
    for j in relevant:
        jid = job_id(j)
        if jid in seen_now:
            continue
        seen_now[jid] = True
        if jid not in state:
            fresh.append(j)
            state[jid] = datetime.now(timezone.utc).isoformat()

    log.info("%d are new since last run", len(fresh))

    if args.dry_run:
        for j in relevant[:20]:
            flag = "NEW " if job_id(j) in {job_id(x) for x in fresh} else "    "
            print(f"{flag}{j['company'][:22]:<22} {j['title'][:48]:<48} {j['location'][:26]}")
        log.info("dry run, nothing saved or sent")
        return 0

    if fresh:
        delivered = send_telegram(fresh)
        if delivered and delivered < len(fresh):
            # anything past the message cap was never seen, so forget it and
            # let the next run offer it again
            for j in fresh[delivered:]:
                state.pop(job_id(j), None)
            log.warning("%d role(s) were not sent and will be retried next run",
                        len(fresh) - delivered)
        if not delivered:
            # Do not remember these. If the alert did not reach you, the
            # next run should try again rather than silently swallowing them.
            log.error("alert not delivered, leaving state untouched so these "
                      "roles are retried next run")
            return 1
    else:
        log.info("nothing new, no alert sent")

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
