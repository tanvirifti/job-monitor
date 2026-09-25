"""
What to look for, and what to ignore.

Everything you would want to change day to day lives here, so you never
have to touch the scraping code.
"""

# ---------------------------------------------------------------- searches

# One set per weekday. Monday is 0. The free Adzuna tier allows 1,000 calls
# a month, so running every search every day is not affordable. Splitting
# them across the week covers 56 distinct searches at roughly 420 calls a
# month, which leaves headroom.
# Weighted to the target order: Data Engineer first, then Data Analyst and
# BI, then everything else. Three of the seven days are given to data
# engineering, two to analyst and BI, and the remaining two carry entry
# routes and the public sector, both still engineering-first.
#
# Monday is 0.
# Run every single day, regardless of rotation.
#
# The rotating sets below cover far more ground, but a term in Tuesday's set
# will not run again until the following Tuesday. Since the lookback window
# is seven days nothing is lost outright, but a role posted on Wednesday
# would wait six days to be seen, and rolling schemes fill inside a
# fortnight. These few terms are too important to wait.
ADZUNA_DAILY_CORE = [
    "graduate data engineer",
    "junior data engineer",
    "graduate data analyst",
    "junior data analyst",
]

ADZUNA_QUERY_SETS = {
    # ---------- PRIMARY: data engineering, three days ----------
    0: [  # Monday - data engineering job titles
        "graduate data engineer",
        "junior data engineer",
        "data engineering graduate",
        "trainee data engineer",
        "entry level data engineer",
        "analytics engineer",
        "junior analytics engineer",
        "data platform engineer graduate",
    ],
    1: [  # Tuesday - data engineering by the work, since many roles are
          # advertised by what you build rather than by the title
        "etl developer junior",
        "etl engineer graduate",
        "data pipeline engineer graduate",
        "data warehouse developer junior",
        "database developer graduate",
        "sql developer graduate",
        "junior python developer",
        "data integration developer junior",
    ],
    2: [  # Wednesday - data engineering by platform and tooling
        "azure data engineer graduate",
        "aws data engineer graduate",
        "cloud data engineer graduate",
        "databricks graduate",
        "snowflake developer junior",
        "spark engineer graduate",
        "big data graduate",
        "graduate software engineer data",
    ],

    # ---------- SECONDARY: analyst and BI, two days ----------
    3: [  # Thursday - data analyst
        "graduate data analyst",
        "junior data analyst",
        "entry level data analyst",
        "trainee data analyst",
        "assistant data analyst",
        "graduate data scientist",
        "data graduate scheme",
        "graduate analyst",
    ],
    4: [  # Friday - business intelligence and reporting
        "business intelligence analyst",
        "bi analyst",
        "bi developer junior",
        "insight analyst",
        "reporting analyst",
        "mi analyst",
        "performance analyst",
        "data officer",
    ],

    # ---------- REMAINDER: entry routes and public sector ----------
    5: [  # Saturday - internships, placements, apprenticeships,
          # engineering listed first
        "data engineer intern",
        "data engineering placement",
        "software engineering placement",
        "data analyst intern",
        "data internship",
        "industrial placement data",
        "degree apprenticeship data",
        "early careers data",
    ],
    6: [  # Sunday - public sector, statistics, and a sweep before Monday
        "statistician",
        "assistant statistician",
        "statistical officer",
        "operational research analyst",
        "digital data technology graduate",
        "graduate scheme technology",
        "data engineer",
        "graduate data analyst",
    ],
}

# Blank means the whole of Great Britain.
#
# London-only was the first setting and it was wrong: several Tier 1
# employers are not in London at all. ONS is in Newport and Titchfield, the
# Met Office is in Exeter, the Environment Agency is in Bristol. Graduate
# schemes are also commonly advertised UK-wide with the office decided
# later. Restricting to London silently removed all of that.
#
# Set this to a city name only if you want to narrow it back down.
ADZUNA_WHERE = ""

# How far back to look on each run. Seven days gives a safety margin if a
# run fails; duplicates get filtered out anyway.
# Ten days rather than seven. The rotation cycle is seven, so seven would
# leave no margin: one failed run and a posting could slip through the gap
# between one appearance of a query and the next.
ADZUNA_MAX_DAYS_OLD = 10

# Tier 1 employers, searched by name through Adzuna. Scraping Civil
# Service Jobs directly was tried first and returned nothing; its markup
# is not stable enough to depend on. Adzuna indexes these employers
# already, so asking it by name is both simpler and harder to break.
PUBLIC_SECTOR_EMPLOYERS = [
    "Office for National Statistics",
    "Civil Service data",
    "NHS data analyst",
    "Transport for London analyst",
    "Met Office data",
    "Environment Agency data",
]

# ---------------------------------------------------------------- filtering

# A title needs at least one of these to be worth showing you.
INCLUDE_WORDS = [
    # ---- PRIMARY: data engineering ----
    "data engineer", "data engineering", "analytics engineer",
    "etl developer", "etl engineer", "data pipeline", "data platform",
    "data warehouse", "data integration", "database developer",
    "sql developer", "python developer", "software engineer",
    "backend developer", "big data", "spark", "databricks",
    "snowflake", "airflow", "dbt", "cloud engineer",
    "azure data", "aws data", "gcp data", "data ops", "dataops",

    # ---- SECONDARY: data analyst ----
    "data analyst", "data scientist", "data officer",
    "data technician", "data administrator", "data specialist",
    "analytics", "decision scientist",

    # ---- SECONDARY: business intelligence ----
    "business intelligence", "bi analyst", "bi developer", "bi engineer",
    "insight analyst", "insights analyst", "reporting analyst",
    "mi analyst", "management information", "performance analyst",
    "information analyst", "dashboard developer",
    "data visualisation", "data visualization",

    # ---- REMAINDER: statistics, research, adjacent ----
    "statistician", "statistical", "operational research",
    "quantitative analyst", "research analyst", "econometric",
    "machine learning", "ml engineer",
    "business analyst", "product analyst", "operations analyst",
    "commercial analyst", "pricing analyst", "customer insight",

    # ---- entry route markers, apply across all of the above ----
    "graduate", "junior", "trainee", "entry level", "entry-level",
    "early careers", "early-careers", "placement", "apprentice",
    "apprenticeship", "intern", "internship", "summer intern",
    "industrial placement", "work experience", "sandwich", "assistant",
    "associate", "scheme", "programme", "rotational", "fast stream",
]

# Any of these and it is not a role you can take yet. Checked with spaces
# around the title so "lead" does not match "leadership" by accident.
EXCLUDE_WORDS = [
    # seniority
    "senior", "lead", "principal", "director", "head of", "manager",
    "chief", "staff", "architect", "vp", "vice president",
    "supervisor", "team leader", "ii", "iii", "iv",
    "level 2", "level 3", "grade 7", "band 7", "band 8",

    # the word "analyst" drags in whole fields that are not yours
    "credit analyst", "risk analyst", "compliance analyst",
    "security analyst", "soc analyst", "cyber analyst",
    "fraud analyst", "aml analyst", "kyc analyst",
    "treasury analyst", "actuarial", "underwriting",
    "clinical", "laboratory", "biomedical",
    "policy analyst", "geospatial surveyor",
    # note: "intelligence analyst" is deliberately NOT excluded. It would
    # also block "business intelligence analyst", which is a core target.

    # not analysis at all
    "executive assistant", "personal assistant", "receptionist",
    "sales", "account executive", "business development",
    "marketing", "seo", "social media",
    "recruiter", "recruitment consultant", "talent acquisition",
    "nurse", "teacher", "lecturer", "driver", "chef",
    "warehouse operative", "warehouse assistant", "warehouse manager",
    # note: bare "warehouse" is NOT excluded. It would block
    # "data warehouse developer", which is a core data engineering title.

    # arrangement you cannot take
    "contract", "interim", "fractional", "freelance",
]

# Adzuna and Civil Service Jobs both return roles outside the UK sometimes.
# If a location contains one of these, drop it.
EXCLUDE_LOCATIONS = [
    "lisbon", "portugal", "porto", "riga", "latvia", "vilnius", "lithuania",
    "tallinn", "estonia", "barcelona", "madrid", "spain", "valencia",
    "dublin", "ireland", "cork", "amsterdam", "netherlands", "rotterdam",
    "berlin", "munich", "hamburg", "germany", "frankfurt",
    "paris", "france", "lyon", "warsaw", "krakow", "poland", "wroclaw",
    "bucharest", "romania", "cluj", "sofia", "bulgaria", "prague",
    "budapest", "hungary", "milan", "rome", "italy", "athens", "greece",
    "stockholm", "sweden", "copenhagen", "denmark", "oslo", "norway",
    "helsinki", "finland", "zurich", "geneva", "switzerland",
    "vienna", "austria", "brussels", "belgium", "luxembourg",
    "india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai",
    "delhi", "gurgaon", "gurugram", "chennai", "kolkata", "noida",
    "united states", "usa", "new york", "austin", "san francisco",
    "seattle", "chicago", "boston", "atlanta", "denver", "texas",
    "california", "remote (us", "canada", "toronto", "vancouver",
    "singapore", "hong kong", "tokyo", "japan", "shanghai", "beijing",
    "sydney", "melbourne", "australia", "auckland", "new zealand",
    "dubai", "abu dhabi", "uae", "qatar", "riyadh",
    "cape town", "johannesburg", "nairobi", "lagos", "cairo",
    "sao paulo", "brazil", "mexico city", "buenos aires", "bogota",
]

# ---------------------------------------------------------------- housekeeping

# How long to remember a job before forgetting it. Anything older than
# this drops out of the state file so it does not grow forever.
FORGET_AFTER_DAYS = 60

# Cap on how many roles go into one alert message, so a busy morning does
# not produce something unreadable.
MAX_PER_ALERT = 25
