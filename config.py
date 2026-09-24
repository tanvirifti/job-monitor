"""
What to look for, and what to ignore.

Everything you would want to change day to day lives here, so you never
have to touch the scraping code.
"""

# ---------------------------------------------------------------- searches

# Each of these becomes one Adzuna API call. Free tier is 1,000 calls a
# month; running twice a day with this many queries uses about 480.
ADZUNA_QUERIES = [
    "graduate data analyst",
    "junior data analyst",
    "graduate business intelligence",
    "graduate data scientist",
    "data analyst placement",
    "graduate analyst",
    "junior business analyst",
    "graduate scheme data",
    "data analyst intern",
    "data internship",
    "summer internship data",
]

# Where to search. Adzuna treats this as a centre point.
ADZUNA_WHERE = "london"

# How far back to look on each run. Seven days gives a safety margin if a
# run fails; duplicates get filtered out anyway.
ADZUNA_MAX_DAYS_OLD = 7

# Civil Service Jobs search terms. This one site carries ONS, Cabinet
# Office, DWP, HMRC, DfT, MoJ, Ofcom, Environment Agency and the Met
# Office, which is most of your Tier 1 list.
CIVIL_SERVICE_QUERIES = [
    "data analyst",
    "graduate",
    "statistician",
    "data scientist",
    "intern",
    "placement",
]

# ---------------------------------------------------------------- filtering

# A title needs at least one of these to be worth showing you.
INCLUDE_WORDS = [
    "graduate", "junior", "trainee", "entry level", "entry-level",
    "early careers", "placement", "apprentice",
    "intern", "internship", "summer intern", "industrial placement",
    "work experience", "sandwich",
    "data analyst", "data scientist", "business intelligence", "bi analyst",
    "insight analyst", "reporting analyst", "mi analyst", "analytics",
    "statistician", "data engineer",
]

# Any of these and it is not a role you can take yet. Checked with spaces
# around the title so "lead" does not match "leadership" by accident.
EXCLUDE_WORDS = [
    "senior", "lead ", " lead", "principal", "director", "head of",
    "manager", "chief", "staff ", "architect", "vp ", "vice president",
    " ii", " iii", " iv", " v ", "level 2", "level 3",
    "contract", "interim", "fractional",
    # not your field, but the word "analyst" pulls them in
    "credit analyst", "risk analyst", "compliance analyst",
    "security analyst", "soc analyst", "cyber analyst",
    "executive assistant", "sales", "marketing", "recruit",
    "clinical", "laboratory", "care ",
]

# Adzuna and Civil Service Jobs both return roles outside the UK sometimes.
# If a location contains one of these, drop it.
EXCLUDE_LOCATIONS = [
    "lisbon", "portugal", "riga", "latvia", "barcelona", "spain",
    "dublin", "ireland", "amsterdam", "netherlands", "berlin", "germany",
    "paris", "france", "warsaw", "poland", "bucharest", "romania",
    "india", "bangalore", "hyderabad", "pune", "mumbai", "gurgaon",
    "united states", "usa", "new york", "austin", "san francisco",
    "singapore", "hong kong", "sydney", "australia", "canada", "toronto",
]

# ---------------------------------------------------------------- housekeeping

# How long to remember a job before forgetting it. Anything older than
# this drops out of the state file so it does not grow forever.
FORGET_AFTER_DAYS = 60

# Cap on how many roles go into one alert message, so a busy morning does
# not produce something unreadable.
MAX_PER_ALERT = 25
