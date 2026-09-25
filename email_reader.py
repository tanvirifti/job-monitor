"""
Reads the job-alert inbox and pulls out the roles.

LinkedIn, Bright Network, Gradcracker and the rest send alerts by email and
offer no API. Rather than scrape each site, all their alerts are pointed at
one Gmail address and read from here. If any of them redesigns their site
this keeps working, because an email is an email.

Needs two environment variables. Without them it returns nothing and the
rest of the run carries on as normal.

    GMAIL_ADDRESS
    GMAIL_APP_PASSWORD      16 characters, from Google account security
"""

import email
import imaplib
import logging
import os
import re
from email.header import decode_header, make_header
from html import unescape

log = logging.getLogger("monitor.email")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

# Senders worth reading. Anything else in the inbox is left alone.
ALERT_SENDERS = [
    "linkedin.com",
    "brightnetwork.co.uk",
    "gradcracker.com",
    "targetjobs.co.uk",
    "milkround.com",
    "civilservicejobs.service.gov.uk",
    "jobs.nhs.uk",
    "prospects.ac.uk",
]

# Tracking and unsubscribe links that are not jobs.
JUNK_LINK = re.compile(
    r"(unsubscribe|preferences|privacy|terms|help|settings|"
    r"optout|opt-out|manage|profile|feedback|survey|"
    r"facebook|twitter|instagram|youtube|apple\.com|play\.google)",
    re.I,
)

# Links that usually are a job. Each site shapes its urls differently:
# Gradcracker puts them under /search/<discipline>/, LinkedIn under
# /jobs/view/, Civil Service uses a jcode query. A title still has to pass
# the keyword filter afterwards, so this can afford to be generous.
JOB_LINK = re.compile(
    r"(/jobs?/|/vacanc|/graduate-jobs?/|/opportunit|/search/|/role/|"
    r"/position|/career|/intern|/placement|/scheme|/apply|/listing|"
    r"jobId=|currentJobId=|jcode=|/job-detail|/job_detail|/adverts?/|"
    r"/jobadvert|/candidate/)",
    re.I,
)


def _decode(raw):
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return raw or ""


def _body_text(msg):
    """Prefer plain text; fall back to stripping tags out of the HTML part."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            try:
                text = payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace")
            except Exception:
                continue
            if part.get_content_type() == "text/plain":
                plain += text
            elif part.get_content_type() == "text/html":
                html += text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            plain = payload.decode(msg.get_content_charset() or "utf-8",
                                   errors="replace")
    return plain, html


def _links_with_text(html):
    """
    Pull (url, anchor text) pairs out of the HTML. Alert emails put the job
    title in the anchor, which is exactly what the filter needs.
    """
    out = []
    for m in re.finditer(
        r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S
    ):
        url, inner = m.group(1), m.group(2)
        title = unescape(re.sub(r"<[^>]+>", " ", inner))
        title = re.sub(r"\s+", " ", title).strip()
        out.append((url, title))
    return out


def fetch_email_alerts(mark_read=True, max_messages=40):
    """
    Returns job dicts in the same shape the rest of the pipeline uses.
    Reads unread mail only, so each alert is processed once.
    """
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        log.info("email alerts skipped, Gmail credentials not set")
        return []

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select("INBOX")
    except Exception as exc:
        log.error("could not open the alert inbox: %s", exc)
        return []

    jobs = []
    try:
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            log.warning("inbox search failed")
            return []

        ids = data[0].split()[-max_messages:]
        log.info("inbox has %d unread message(s) to read", len(ids))

        for num in ids:
            try:
                fetch_flag = "(RFC822)" if mark_read else "(BODY.PEEK[])"
                status, payload = imap.fetch(num, fetch_flag)
                if status != "OK" or not payload or not payload[0]:
                    continue

                msg = email.message_from_bytes(payload[0][1])
                sender = _decode(msg.get("From", "")).lower()

                source = next(
                    (s for s in ALERT_SENDERS if s in sender), None
                )
                if not source:
                    continue

                plain, html = _body_text(msg)
                pairs = _links_with_text(html)

                # plain-text only emails still yield bare urls
                if not pairs and plain:
                    for url in re.findall(r"https?://\S+", plain):
                        pairs.append((url.rstrip(".,)>"), ""))

                seen_urls = set()
                for url, title in pairs:
                    if JUNK_LINK.search(url) or not JOB_LINK.search(url):
                        continue
                    clean = url.split("?")[0]
                    if clean in seen_urls:
                        continue
                    seen_urls.add(clean)
                    if len(title) < 6:
                        continue
                    jobs.append(
                        {
                            "source": pretty_source(source),
                            "company": "",
                            "title": title[:120],
                            "location": "",
                            "url": url,
                            "posted": "",
                        }
                    )

                log.info("  %-26s %2d link(s)", pretty_source(source),
                         len(seen_urls))

            except Exception as exc:
                log.warning("skipped one message: %s", exc)
                continue

    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass

    log.info("email alerts produced %d candidate role(s)", len(jobs))
    return jobs


def pretty_source(domain):
    names = {
        "linkedin.com": "LinkedIn",
        "brightnetwork.co.uk": "Bright Network",
        "gradcracker.com": "Gradcracker",
        "targetjobs.co.uk": "TargetJobs",
        "milkround.com": "Milkround",
        "civilservicejobs.service.gov.uk": "Civil Service Jobs",
        "jobs.nhs.uk": "NHS Jobs",
        "prospects.ac.uk": "Prospects",
    }
    return names.get(domain, domain)
