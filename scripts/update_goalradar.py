import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# GOALRADAR CONFIGURATION
# ============================================================

API_KEY = os.environ.get("API_FOOTBALL_KEY")

BASE_URL = "https://v3.football.api-sports.io"

DATA_FILE = "data/goalradar.json"

# Free API-Football plan:
# Stay below the 10 requests/minute limit.
REQUEST_DELAY = 7

# Keep prediction requests low.
MAX_PREDICTIONS = 6

# Main leagues displayed on GoalRadar.
UPCOMING_LEAGUES = {
    "EPL": 39,
    "La Liga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "Ligue 1": 61,
    "UCL": 2,
}

# 2026 is the active season for the current football calendar.
SEASON = 2026

last_request_time = 0


# ============================================================
# BASIC HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_existing_data():

    try:

        if os.path.exists(DATA_FILE):

            with open(
                DATA_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

    except Exception as e:

        print(
            "Could not load existing data:",
            e
        )

    return {
        "updated_at": None,
        "date": None,

        "stats": {
            "matches_today": 0,
            "analyzed": 0,
            "high_confidence": 0,
            "upcoming_leagues": 0,
        },

        "picks": [],

        "upcoming": {
            key: []
            for key in UPCOMING_LEAGUES
        },
    }


# ============================================================
# API REQUEST FUNCTION
# ============================================================

def get(endpoint, params=None):

    global last_request_time

    if not API_KEY:

        raise RuntimeError(
            "API_FOOTBALL_KEY is missing. "
            "Check your GitHub repository secret."
        )

    url = BASE_URL + endpoint

    if params:

        url += "?" + urlencode(params)

    headers = {
        "x-apisports-key": API_KEY,
        "User-Agent": "GoalRadar/1.0",
    }

    # --------------------------------------------------------
    # Keep requests below the API rate limit.
    # --------------------------------------------------------

    elapsed = time.time() - last_request_time

    if elapsed < REQUEST_DELAY:

        wait = REQUEST_DELAY - elapsed

        print(
            f"Waiting {wait:.1f}s before next API request..."
        )

        time.sleep(wait)

    request = Request(
        url,
        headers=headers,
        method="GET"
    )

    try:

        print(
            f"API request: {endpoint}"
        )

        with urlopen(
            request,
            timeout=30
        ) as response:

            raw = response.read().decode(
                "utf-8"
            )

        last_request_time = time.time()

        data = json.loads(raw)

        # ----------------------------------------------------
        # API-Football sometimes returns errors inside JSON.
        # ----------------------------------------------------

        if data.get("errors"):

            errors = data["errors"]

            print(
                "API returned errors:",
                errors
            )

            error_text = str(
                errors
            ).lower()

            if (
                "request limit" in error_text
                or "too many requests" in error_text
                or "rate limit" in error_text
            ):

                print(
                    "API request limit reached."
                )

                return None

        return data

    except HTTPError as e:

        last_request_time = time.time()

        if e.code == 429:

            print(
                "HTTP 429: API rate/request limit reached."
            )

            print(
                "GoalRadar will keep existing data."
            )

            return None

        if e.code == 403:

            print(
                "HTTP 403: API access denied."
            )

            return None

        print(
            f"HTTP error {e.code}: {e.reason}"
        )

        return None

    except URLError as e:

        print(
            "Network error:",
            e
        )

        return None

    except Exception as e:

        print(
            "Unexpected API error:",
            e
        )

        return None


# ============================================================
# FIXTURE FILTERING
# ============================================================

def is_good_fixture(fixture):

    league = fixture.get(
        "league",
        {}
    )

    name = str(
        league.get(
            "name",
            ""
        )
    ).lower()

    league_type = str(
        league.get(
            "type",
            ""
        )
    ).lower()

    home = str(
        fixture
        .get("teams", {})
        .get("home", {})
        .get("name", "")
    ).lower()

    away = str(
        fixture
        .get("teams", {})
        .get("away", {})
        .get("name", "")
    ).lower()

    text = (
        f"{name} {home} {away}"
    )

    blocked_words = [

        "women",
        "woman",
        "female",

        "u17",
        "u18",
        "u19",
        "u20",
        "u21",
        "u23",

        "youth",

        "reserve",
        "reserves",

        "friendly",
        "club friendly",
    ]

    for word in blocked_words:

        if word in text:

            return False

    if league_type not in (
        "league",
        "cup"
    ):

        return False

    return True


# ============================================================
# FIXTURE PRIORITY
# ============================================================

def fixture_priority(fixture):

    league = fixture.get(
        "league",
        {}
    )

    league_id = league.get(
        "id"
    )

    name = str(
        league.get(
            "name",
            ""
        )
    ).lower()

    priority_ids = {

        39: 100,   # EPL
        2: 100,    # Champions League

        140: 98,   # La Liga
        135: 96,   # Serie A
        78: 94,    # Bundesliga
        61: 92,    # Ligue 1

        88: 85,    # Eredivisie
        94: 85,    # Primeira Liga
        203: 82,   # Turkey
        144: 82,   # Belgium
        71: 80,    # Brazil
        128: 80,   # Argentina
    }

    score = priority_ids.get(
        league_id,
        10
    )

    important_words = [

        "champions",
        "premier",
        "la liga",
        "serie a",
        "bundesliga",
        "ligue 1",
    ]

    for word in important_words:

        if word in name:

            score += 15

    return score


# ============================================================
# PREDICTION PROCESSING
# ============================================================

def extract_prediction(data):

    if not data:

        return {
            "pick": "Analysis pending",
            "type": "Match",
            "confidence": 0,
        }

    response = data.get(
        "response",
        []
    )

    if not response:

        return {
            "pick": "Analysis pending",
            "type": "Match",
            "confidence": 0,
        }

    prediction = response[0].get(
        "predictions",
        {}
    )

    winner = prediction.get(
        "winner"
    ) or {}

    winner_name = winner.get(
        "name"
    )

    percent = prediction.get(
        "percent"
    ) or {}

    def number(value):

        try:

            return int(
                str(value)
                .replace("%", "")
                .strip()
            )

        except Exception:

            return 0

    home_percent = number(
        percent.get("home")
    )

    draw_percent = number(
        percent.get("draw")
    )

    away_percent = number(
        percent.get("away")
    )

    percentages = [

        ("home", home_percent),
        ("draw", draw_percent),
        ("away", away_percent),
    ]

    percentages.sort(
        key=lambda x: x[1],
        reverse=True
    )

    highest = percentages[0][1]

    if winner_name:

        return {

            "pick":
                f"{winner_name} Win",

            "type":
                "1X2",

            "confidence":
                highest or 60,
        }

    if highest >= 50:

        label = {

            "home":
                "Home Win",

            "draw":
                "Draw",

            "away":
                "Away Win",
        }

        return {

            "pick":
                label[
                    percentages[0][0]
                ],

            "type":
                "1X2",

            "confidence":
                highest,
        }

    return {

        "pick":
            "Analysis pending",

        "type":
            "Match",

        "confidence":
            0,
    }


# ============================================================
# UPCOMING FIXTURES
# ============================================================

def get_upcoming(existing_upcoming):

    upcoming = {
        key: []
        for key in UPCOMING_LEAGUES
    }

    successful = 0

    for display_name, league_id in UPCOMING_LEAGUES.items():

        print(
            f"\nGetting upcoming {display_name}..."
        )

        data = get(
            "/fixtures",
            {
                "league":
                    league_id,

                "season":
                    SEASON,

                "next":
                    10,

                "timezone":
                    "Africa/Accra",
            }
        )

        # ----------------------------------------------------
        # If API fails, preserve previous data.
        # ----------------------------------------------------

        if not data:

            print(
                f"Keeping previous {display_name} data."
            )

            upcoming[display_name] = (
                existing_upcoming.get(
                    display_name,
                    []
                )
            )

            if upcoming[display_name]:

                successful += 1

            continue

        fixtures = data.get(
            "response",
            []
        )

        clean = []

        for fixture in fixtures:

            if not is_good_fixture(
                fixture
            ):

                continue

            status = (
                fixture
                .get("fixture", {})
                .get("status", {})
                .get("short", "")
            )

            if status not in (
                "NS",
                "TBD"
            ):

                continue

            teams = fixture.get(
                "teams",
                {}
            )

            home = (
                teams
                .get("home", {})
                .get("name")
            )

            away = (
                teams
                .get("away", {})
                .get("name")
            )

            fixture_info = (
                fixture.get(
                    "fixture",
                    {}
                )
            )

            venue = (
                fixture_info
                .get("venue")
                or {}
            )

            clean.append({

                "fixture_id":
                    fixture_info.get(
                        "id"
                    ),

                "league":
                    fixture
                    .get("league", {})
                    .get(
                        "name",
                        display_name
                    ),

                "home":
                    home,

                "away":
                    away,

                "kickoff":
                    fixture_info.get(
                        "date"
                    ),

                "venue":
                    venue.get(
                        "name"
                    ) or "Venue TBC",

                "city":
                    venue.get(
                        "city"
                    ),

                "round":
                    fixture
                    .get("league", {})
                    .get(
                        "round"
                    ),
            })

        upcoming[display_name] = (
            clean[:10]
        )

        if clean:

            successful += 1

        print(
            f"{display_name}: "
            f"{len(clean)} upcoming matches"
        )

    return upcoming, successful


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    print("=" * 60)
    print("GOALRADAR UPDATE START")
    print("=" * 60)

    existing = load_existing_data()

    today = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d"
    )

    display_date = datetime.now(
        timezone.utc
    ).strftime(
        "%d %b %Y"
    ).upper()

    # ========================================================
    # 1. TODAY'S FIXTURES
    # ========================================================

    print(
        "\nFetching today's fixtures..."
    )

    fixtures_data = get(
        "/fixtures",
        {
            "date":
                today,

            "timezone":
                "Africa/Accra",
        }
    )

    # --------------------------------------------------------
    # If today's request fails, preserve everything.
    # --------------------------------------------------------

    if fixtures_data is None:

        print(
            "\nAPI unavailable."
        )

        print(
            "Keeping existing GoalRadar data."
        )

        print(
            "No data will be overwritten."
        )

        return

    fixtures = fixtures_data.get(
        "response",
        []
    )

    print(
        f"Today's total fixtures: "
        f"{len(fixtures)}"
    )

    # ========================================================
    # 2. FILTER TODAY'S MATCHES
    # ========================================================

    good_fixtures = [

        fixture

        for fixture in fixtures

        if is_good_fixture(
            fixture
        )
    ]

    good_fixtures.sort(
        key=fixture_priority,
        reverse=True
    )

    selected = good_fixtures[
        :MAX_PREDICTIONS
    ]

    print(
        f"Selected for analysis: "
        f"{len(selected)}"
    )

    # ========================================================
    # 3. GET PREDICTIONS
    # ========================================================

    picks = []

    for index, fixture in enumerate(
        selected,
        start=1
    ):

        fixture_id = (
            fixture
            .get("fixture", {})
            .get("id")
        )

        league = (
            fixture
            .get("league", {})
        )

        teams = (
            fixture
            .get("teams", {})
        )

        home = (
            teams
            .get("home", {})
            .get("name")
        )

        away = (
            teams
            .get("away", {})
            .get("name")
        )

        print(
            f"\nPrediction "
            f"{index}/{len(selected)}:"
        )

        print(
            f"{home} vs {away}"
        )

        prediction_data = get(
            "/predictions",
            {
                "fixture":
                    fixture_id
            }
        )

        prediction = (
            extract_prediction(
                prediction_data
            )
        )

        picks.append({

            "league":
                league.get(
                    "name",
                    "Football"
                ),

            "home":
                home,

            "away":
                away,

            "pick":
                prediction["pick"],

            "type":
                prediction["type"],

            "confidence":
                prediction["confidence"],

            "fixture_id":
                fixture_id,

            "kickoff":
                fixture
                .get("fixture", {})
                .get("date"),
        })

    # ========================================================
    # 4. UPCOMING FIXTURES
    # ========================================================

    print(
        "\nFetching upcoming league fixtures..."
    )

    previous_upcoming = existing.get(
        "upcoming",
        {}
    )

    upcoming, upcoming_count = (
        get_upcoming(
            previous_upcoming
        )
    )

    # ========================================================
    # 5. STATS
    # ========================================================

    analyzed = sum(

        1

        for pick in picks

        if pick.get(
            "confidence",
            0
        ) > 0
    )

    high_confidence = sum(

        1

        for pick in picks

        if pick.get(
            "confidence",
            0
        ) >= 75
    )

    # ========================================================
    # 6. FINAL DATA
    # ========================================================

    output = {

        "updated_at":
            now_iso(),

        "date":
            display_date,

        "stats": {

            "matches_today":
                len(fixtures),

            "analyzed":
                analyzed,

            "high_confidence":
                high_confidence,

            "upcoming_leagues":
                upcoming_count,
        },

        "picks":
            picks,

        "upcoming":
            upcoming,
    }

    # ========================================================
    # 7. SAVE JSON
    # ========================================================

    os.makedirs(
        os.path.dirname(DATA_FILE),
        exist_ok=True
    )

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    # ========================================================
    # 8. SUMMARY
    # ========================================================

    print("\n" + "=" * 60)
    print("GOALRADAR UPDATE COMPLETE")
    print("=" * 60)

    print(
        f"Today's fixtures: "
        f"{len(fixtures)}"
    )

    print(
        f"Today's analyzed picks: "
        f"{analyzed}"
    )

    print(
        f"High confidence picks: "
        f"{high_confidence}"
    )

    print(
        f"Upcoming leagues: "
        f"{upcoming_count}"
    )

    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
