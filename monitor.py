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

    found = []
    for query in config.ADZUNA_QUERIES:
        url = (
            "https://api.adzuna.com/v1/api/jobs/gb/search/1"
            f"?app_id={ADZUNA_ID}&app_key={ADZUNA_KEY}"
            f"&results_per_page=50"
            f"&what={quote_plus(query)}"
            f"&where={quote_plus(config.ADZUNA_WHERE)}"
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
    Civil Service Jobs carries most of the Tier 1 list in one place.

    The site is a CGI application with no documented API, so this reads the
    public search results page. It is the fragile part of the pipeline: if
    they change their markup it stops finding things. It fails quietly on
    purpose, so a broken parse never takes the whole run down.
    """
    base = "https://www.civilservicejobs.service.gov.uk/csr/index.cgi"
    found = []

    for query in config.CIVIL_SERVICE_QUERIES:
        try:
            r = requests.get(
                base,
                params={"pagecode": "search", "searchsort": "closingsoon", "what": query},
                headers=HEADERS,
                timeout=25,
            )
            r.raise_for_status()
            html = r.text
        except Exception as exc:
            log.error("Civil Service query %r failed: %s", query, exc)
            continue

        # Each result sits in a block with a link to a job id.
        pattern = re.compile(
            r'<a[^>]+href="([^"]*jcode=[^"]*)"[^>]*>(.*?)</a>', re.I | re.S
        )
        hits = pattern.findall(html)

        for href, raw_title in hits:
            title = strip_tags(raw_title).strip()
            if not title or len(title) < 6:
                continue
            link = href if href.startswith("http") else (
                "https://www.civilservicejobs.service.gov.uk" + href
            )
            found.append(
                {
                    "source": "Civil Service Jobs",
                    "company": "Civil Service",
                    "title": title,
                    "location": "UK",
                    "url": link,
                    "posted": "",
                }
            )

        log.info("CivilService %-30r %3d raw hits", query, len(hits))
        time.sleep(0.6)

    return found


def strip_tags(text):
    return re.sub(r"<[^>]+>", "", text or "").replace("&amp;", "&").strip()


# ----------------------------------------------------------------- alerting


def send_telegram(jobs):
    if not (TG_TOKEN and TG_CHAT):
        log.warning("Telegram not configured, printing instead")
        for j in jobs:
            print(f"  {j['company']} | {j['title']} | {j['location']}\n    {j['url']}")
        return False

    shown = jobs[: config.MAX_PER_ALERT]
    extra = len(jobs) - len(shown)

    lines = [f"*{len(jobs)} new role{'s' if len(jobs) != 1 else ''}*", ""]
    for j in shown:
        title = escape_md(j["title"])
        company = escape_md(j["company"])
        loc = escape_md(j["location"][:38])
        lines.append(f"*{title}*")
        lines.append(f"{company} · {loc} · _{j['source']}_")
        lines.append(j["url"])
        lines.append("")
    if extra:
        lines.append(f"_and {extra} more_")

    text = "\n".join(lines)[:4000]

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": TG_CHAT,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        log.info("alert sent to Telegram")
        return True
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)
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
        send_telegram(fresh)
    else:
        log.info("nothing new, no alert sent")

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
