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
   ├── Adzuna API          11 role searches across UK job boards
   ├── Adzuna by employer  6 Tier 1 public sector employers by name
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
and its free tier allows 1,000 calls a month; this uses about 510.

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

Everything you would want to change is in `config.py`:

- `ADZUNA_QUERIES` — the searches. Each one is an API call, so keep an eye
  on the monthly budget if you add many.
- `INCLUDE_WORDS` / `EXCLUDE_WORDS` — what counts as relevant. The exclude
  list is doing most of the work: without it, searching "analyst" returns
  mostly senior and credit-risk roles.
- `EXCLUDE_LOCATIONS` — both sources return non-UK roles.

After changing the filter, run `--dry-run` and read the output before
letting it send anything.

## Known limits

**Everything depends on Adzuna.** One source means one point of failure. If
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
