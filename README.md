# Job monitor

Checks UK job sources twice a day for graduate and junior data roles, and
sends a Telegram message when something new appears. Runs on GitHub Actions,
so it keeps working with the laptop shut.

Built because the 2027 graduate cycle opens in autumn and rolling schemes
fill within days of opening. Hearing about a posting the morning it goes
live is worth more than checking twenty career pages by hand each week.

## What it does

```
GitHub Actions (07:00 UK, daily)
   │
   ├── Adzuna API          55 searches, rotated across the week
   ├── Adzuna by employer  6 Tier 1 public sector employers by name
   ├── Alert inbox         LinkedIn, Bright Network, Gradcracker,
   │                       TargetJobs, Milkround, Civil Service, NHS
   │
   ├── filter              drops senior roles and anything outside the UK
   ├── compare             against seen_jobs.json, committed back each run
   │
   └── Telegram            only if something is genuinely new
```

No database, no browser, no scraping infrastructure. Two HTTP sources and a
JSON file.

## Why these sources

An earlier version tried reading careers pages directly from a list of
21,609 licensed visa sponsors. The arithmetic kills it: checking each site
once a day is 648,000 requests a month, and GitHub's free runner budget
covers roughly two full passes, not sixty. Many of those sites also render
their listings in JavaScript, which needs a headless browser and turns a
free job into a few hundred pounds a month.

Aggregators already did that crawl. Adzuna covers thousands of UK employers
and its free tier allows 1,000 calls a month; this uses about 540.

Civil Service Jobs was the original second source, since it carries most of
the Tier 1 list in one place. Scraping it returned nothing on the first run
and its markup is not stable enough to keep guessing at, so those employers
are now searched by name through Adzuna instead. An aggregator that
publishes an API is a safer dependency than a page scrape.

## Setup

### 1. Adzuna key

Register at [developer.adzuna.com](https://developer.adzuna.com). Free,
instant, no card. Copy the App ID and App Key from the dashboard.

### 2. Telegram bot

1. Open Telegram, message [@BotFather](https://t.me/botfather)
2. Send `/newbot`, pick a name
3. Copy the token it gives you
4. Message your new bot once (it cannot message you first)
5. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   and copy the `chat.id` value

### 3. GitHub secrets

In the repo: Settings → Secrets and variables → Actions → New repository
secret. Add four:

| Name | Value |
|---|---|
| `ADZUNA_APP_ID` | from step 1 |
| `ADZUNA_APP_KEY` | from step 1 |
| `TELEGRAM_BOT_TOKEN` | from step 2 |
| `TELEGRAM_CHAT_ID` | from step 2 |
| `GMAIL_ADDRESS` | the alert inbox, optional |
| `GMAIL_APP_PASSWORD` | 16-char app password, optional |

Keys go in secrets, never in the code.

### 4. First run

Actions tab → "Check for new jobs" → Run workflow. The first run alerts on
everything it finds, because nothing has been seen yet. After that it only
tells you about genuinely new postings.

## Running locally

```bash
pip install -r requirements.txt

export ADZUNA_APP_ID=...
export ADZUNA_APP_KEY=...

python monitor.py --dry-run   # fetch and filter, change nothing
python monitor.py             # normal run
```

`--dry-run` is the one to use while tuning the filter.

## Tuning

Everything you would want to change is in `config.py`.

**`ADZUNA_DAILY_CORE`** — four terms that run every day regardless of
rotation. Keep this short; every entry costs 30 calls a month.

**`ADZUNA_QUERY_SETS`** — one set per weekday, Monday is 0. Fifty-five
searches in total, weighted to the target order: Monday to Wednesday data
engineering, Thursday and Friday analyst and BI, Saturday and Sunday entry
routes and public sector.

Three days on data engineering because those roles are advertised three
ways: by title (data engineer, analytics engineer), by the work (ETL,
pipelines, warehousing), and by platform (Azure, Databricks, Snowflake).
Searching the title alone misses most of the other two.

**`ADZUNA_MAX_DAYS_OLD`** — ten days. Deliberately longer than the
seven-day rotation, so a rotating term still catches anything posted since
it last ran, even if a run fails.

**`ADZUNA_WHERE`** — blank means the whole of Great Britain. London-only
was the original setting and it was wrong: ONS is in Newport, the Met
Office in Exeter, the Environment Agency in Bristol.

**`INCLUDE_WORDS` and `EXCLUDE_WORDS`** — what counts as relevant. The
exclude list does most of the work; without it, searching "analyst" returns
mostly senior and credit-risk roles.

Two traps worth knowing about, both found the hard way. A broad exclude
term can silently kill a target title: `intelligence analyst` also blocks
`business intelligence analyst`, and bare `warehouse` also blocks
`data warehouse developer`. Matching is on word boundaries, so `intern`
no longer catches `internal auditor`, but check any new exclude term
against your own target titles before adding it.

After changing the filter, run `--dry-run` and read the output before
letting it send anything.

## Known limits

**Sites that publish no API are read by email instead.** LinkedIn, Bright
Network, Gradcracker and the rest all offer their own alerts, so those are
pointed at one inbox and read over IMAP. That is more robust than scraping
seven sites, and it survives their redesigns. The trade-off is that alerts
arrive on each site's schedule rather than instantly.

**Alerts are split across several messages when there are many.** Telegram
caps a message at 4,096 characters. An early version cut the text there,
which quietly dropped 131 roles out of a 153-role batch while still marking
all of them as seen, so they were never offered again. The sender now packs
roles into as many messages as it takes and reports how many actually went
out, and only those are recorded.

**Adzuna is still the single biggest dependency.** One source means one point of failure. If
their index lags or the free tier changes, the whole thing goes quiet. Worth
glancing at the Actions log now and then rather than reading silence as
"nothing is being advertised".

**Adzuna's index is not instant.** A posting can appear on a company site
some hours before it reaches the aggregator. For the handful of employers
that matter most, checking directly is still worth doing.

**The filter is deliberately strict.** It would rather miss a borderline
role than bury a real one under noise. If it goes quiet for a week during
the autumn cycle, loosen `EXCLUDE_WORDS` before assuming nothing is being
advertised.
