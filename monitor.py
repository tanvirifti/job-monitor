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
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as exc:
            log.error("Adzuna query %r failed: %s", query, exc)
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
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as exc:
            log.error("public sector query %r failed: %s", employer, exc)
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


def send_telegram(jobs):
    """
    Sends a plain-text message. Telegram's Markdown mode rejects perfectly
    ordinary job titles (brackets, underscores, stray asterisks), which is
    what produced a 400 on the first run. Plain text cannot fail that way.

    Returns True only if the message actually went out, so the caller knows
    whether it is safe to mark these jobs as seen.
    """
    if not (TG_TOKEN and TG_CHAT):
        log.warning("Telegram not configured, printing instead")
        for j in jobs:
            print(f"  {j['company']} | {j['title']} | {j['location']}\n    {j['url']}")
        return False

    shown = jobs[: config.MAX_PER_ALERT]
    extra = len(jobs) - len(shown)

    lines = [f"{len(jobs)} new role{'s' if len(jobs) != 1 else ''}", ""]
    for j in shown:
        lines.append(j["title"])
        bits = [b for b in (j["company"], j["location"][:38], j["source"]) if b]
        lines.append(" | ".join(bits))
        lines.append(j["url"])
        lines.append("")
    if extra:
        lines.append(f"and {extra} more")

    text = "\n".join(lines)[:4000]

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": TG_CHAT,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code != 200:
            # the body says exactly what Telegram objected to
            log.error("Telegram refused the message: %s %s",
                      r.status_code, r.text[:300])
            return False
        log.info("alert sent to Telegram")
        return True
    except Exception as exc:
        log.error("Telegram request failed: %s", exc)
        return False


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
