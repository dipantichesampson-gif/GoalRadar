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

REQUEST_DELAY = 7
MAX_PREDICTIONS = 6

UPCOMING_LEAGUES = {
    "EPL": 39,
    "La Liga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "Ligue 1": 61,
    "UCL": 2,
}

# Keep this as the requested current season.
# The API may deny access depending on your subscription.
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
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            data.setdefault("stats", {})
            data.setdefault("picks", [])
            data.setdefault("upcoming", {})

            for name in UPCOMING_LEAGUES:
                data["upcoming"].setdefault(name, [])

            return data

    except (OSError, json.JSONDecodeError) as e:
        print("Could not load existing data:", e)

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
            name: [] for name in UPCOMING_LEAGUES
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

    request = Request(
        url,
        headers={
            "x-apisports-key": API_KEY,
            "User-Agent": "GoalRadar/1.2",
        },
        method="GET",
    )

    elapsed = time.time() - last_request_time

    if elapsed < REQUEST_DELAY:
        wait = REQUEST_DELAY - elapsed
        print(f"Waiting {wait:.1f}s before next API request...")
        time.sleep(wait)

    try:
        print(f"API request: {endpoint} {params or {}}")

        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")

        last_request_time = time.time()
        data = json.loads(raw)

        errors = data.get("errors")
        if errors:
            print("API returned errors:", errors)
            return None

        return data

    except HTTPError as e:
        last_request_time = time.time()
        print(f"HTTP error {e.code}: {e.reason}")

        try:
            print(e.read().decode("utf-8")[:1000])
        except Exception:
            pass

        return None

    except URLError as e:
        print("Network error:", e)
        return None

    except (ValueError, OSError) as e:
        print("API response error:", e)
        return None


# ============================================================
# FIXTURE FILTERING
# ============================================================

def is_good_fixture(fixture, diagnostic=False):
    league = fixture.get("league") or {}
    teams = fixture.get("teams") or {}

    home = str(
        (teams.get("home") or {}).get("name") or ""
    ).lower()

    away = str(
        (teams.get("away") or {}).get("name") or ""
    ).lower()

    name = str(league.get("name") or "").lower()
    league_type = str(league.get("type") or "").lower().strip()

    if diagnostic:
        print(
            f"League: {league.get('name')} | "
            f"Type: {league.get('type')!r} | "
            f"Country: {league.get('country')}"
        )

    text = f"{name} {home} {away}"

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
        "club friendly",
        "women's",
    ]

    if any(word in text for word in blocked_words):
        if diagnostic:
            print("  Rejected: youth, women's, or reserve competition")
        return False

    # Missing league.type is allowed because fixture responses may omit it.
    # If a type is present, reject only explicitly unsupported types.
    if league_type and league_type not in ("league", "cup"):
        if diagnostic:
            print("  Rejected: unsupported league type:", league_type)
        return False

    # Avoid accepting incomplete fixtures.
    if not home or not away:
        if diagnostic:
            print("  Rejected: missing home or away team")
        return False

    return True


# ============================================================
# FIXTURE PRIORITY
# ============================================================

def fixture_priority(fixture):
    league = fixture.get("league") or {}
    league_id = league.get("id")
    name = str(league.get("name") or "").lower()

    priority_ids = {
        39: 100,
        2: 100,
        140: 98,
        135: 96,
        78: 94,
        61: 92,
        88: 85,
        94: 85,
        203: 82,
        144: 82,
        71: 80,
        128: 80,
    }

    score = priority_ids.get(league_id, 10)

    important_words = [
        "champions",
        "premier",
        "la liga",
        "serie a",
        "bundesliga",
        "ligue 1",
    ]

    if any(word in name for word in important_words):
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

    response = data.get("response") or []
    if not response:
        return {
            "pick": "Analysis pending",
            "type": "Match",
            "confidence": 0,
        }

    prediction = response[0].get("predictions") or {}
    winner = prediction.get("winner") or {}
    winner_name = winner.get("name")
    percent = prediction.get("percent") or {}

    def number(value):
        try:
            return int(str(value).replace("%", "").strip())
        except (ValueError, TypeError):
            return 0

    percentages = {
        "home": number(percent.get("home")),
        "draw": number(percent.get("draw")),
        "away": number(percent.get("away")),
    }

    best = max(percentages, key=percentages.get)
    highest = percentages[best]

    if winner_name:
        return {
            "pick": f"{winner_name} Win",
            "type": "1X2",
            "confidence": highest or 60,
        }

    if highest >= 50:
        labels = {
            "home": "Home Win",
            "draw": "Draw",
            "away": "Away Win",
        }

        return {
            "pick": labels[best],
            "type": "1X2",
            "confidence": highest,
        }

    return {
        "pick": "Analysis pending",
        "type": "Match",
        "confidence": 0,
    }


# ============================================================
# UPCOMING FIXTURES
# ============================================================

def get_upcoming(existing_upcoming):
    upcoming = {}
    successful = 0

    for display_name, league_id in UPCOMING_LEAGUES.items():
        print(f"\nGetting upcoming {display_name}...")

        data = get(
            "/fixtures",
            {
                "league": league_id,
                "season": SEASON,
                "next": 10,
                "timezone": "Africa/Accra",
            },
        )

        previous = existing_upcoming.get(display_name, [])

        # If API access fails, retain cached fixtures.
        if data is None:
            print(f"Keeping previous {display_name} data.")
            upcoming[display_name] = previous

            if previous:
                successful += 1
            continue

        fixtures = data.get("response") or []
        clean = []

        for fixture in fixtures:
            if not is_good_fixture(fixture):
                continue

            fixture_info = fixture.get("fixture") or {}
            status = (
                (fixture_info.get("status") or {}).get("short") or ""
            )

            if status not in ("NS", "TBD"):
                continue

            teams = fixture.get("teams") or {}
            home = (teams.get("home") or {}).get("name")
            away = (teams.get("away") or {}).get("name")

            if not home or not away:
                continue

            venue = fixture_info.get("venue") or {}
            league = fixture.get("league") or {}

            clean.append({
                "fixture_id": fixture_info.get("id"),
                "league": league.get("name", display_name),
                "home": home,
                "away": away,
                "kickoff": fixture_info.get("date"),
                "venue": venue.get("name") or "Venue TBC",
                "city": venue.get("city"),
                "round": league.get("round"),
            })

        # Don't erase cached matches just because a successful response
        # contained no usable fixtures.
        if clean:
            upcoming[display_name] = clean[:10]
            successful += 1
        else:
            upcoming[display_name] = previous
            if previous:
                successful += 1
            print(
                f"{display_name}: no usable fixtures returned; "
                f"keeping {len(previous)} cached matches"
            )

        print(
            f"{display_name}: "
            f"{len(upcoming[display_name])} upcoming matches"
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

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    display_date = now.strftime("%d %b %Y").upper()

    # --------------------------------------------------------
    # 1. Fetch today's fixtures
    # --------------------------------------------------------

    print("\nFetching today's fixtures...")

    fixtures_data = get(
        "/fixtures",
        {
            "date": today,
            "timezone": "Africa/Accra",
        },
    )

    # Don't overwrite the data file if today's API request fails.
    if fixtures_data is None:
        print("Today's fixture request failed.")
        print("Keeping existing GoalRadar data.")
        return

    fixtures = fixtures_data.get("response") or []
    print(f"Today's total fixtures: {len(fixtures)}")

    # --------------------------------------------------------
    # 2. Diagnose the filter
    # --------------------------------------------------------

    print("\nChecking the first 10 fixture league types:")

    for fixture in fixtures[:10]:
        is_good_fixture(fixture, diagnostic=True)

    good_fixtures = [
        fixture for fixture in fixtures
        if is_good_fixture(fixture)
    ]

    print("Fixtures after filtering:", len(good_fixtures))

    good_fixtures.sort(
        key=fixture_priority,
        reverse=True,
    )

    selected = good_fixtures[:MAX_PREDICTIONS]
    print(f"Selected for analysis: {len(selected)}")

    # --------------------------------------------------------
    # 3. Fetch predictions
    # --------------------------------------------------------

    picks = []

    for index, fixture in enumerate(selected, start=1):
        fixture_info = fixture.get("fixture") or {}
        fixture_id = fixture_info.get("id")
        league = fixture.get("league") or {}
        teams = fixture.get("teams") or {}

        home = (teams.get("home") or {}).get("name")
        away = (teams.get("away") or {}).get("name")

        if not fixture_id or not home or not away:
            print("Skipping fixture with incomplete information.")
            continue

        print(f"\nPrediction {index}/{len(selected)}:")
        print(f"{home} vs {away}")

        prediction_data = get(
            "/predictions",
            {"fixture": fixture_id},
        )

        prediction = extract_prediction(prediction_data)

        picks.append({
            "league": league.get("name", "Football"),
            "home": home,
            "away": away,
            "pick": prediction["pick"],
            "type": prediction["type"],
            "confidence": prediction["confidence"],
            "fixture_id": fixture_id,
            "kickoff": fixture_info.get("date"),
        })

    # --------------------------------------------------------
    # 4. Fetch upcoming fixtures
    # --------------------------------------------------------

    print("\nFetching upcoming league fixtures...")

    previous_upcoming = existing.get("upcoming") or {}
    upcoming, upcoming_count = get_upcoming(previous_upcoming)

    # --------------------------------------------------------
    # 5. Calculate stats
    # --------------------------------------------------------

    analyzed = sum(
        1 for pick in picks if pick.get("confidence", 0) > 0
    )

    high_confidence = sum(
        1 for pick in picks if pick.get("confidence", 0) >= 75
    )

    # --------------------------------------------------------
    # 6. Prepare output
    # --------------------------------------------------------

    output = {
        "updated_at": now_iso(),
        "date": display_date,
        "stats": {
            "matches_today": len(fixtures),
            "analyzed": analyzed,
            "high_confidence": high_confidence,
            "upcoming_leagues": upcoming_count,
        },
        "picks": picks,
        "upcoming": upcoming,
    }

    # --------------------------------------------------------
    # 7. Save output
    # --------------------------------------------------------

    directory = os.path.dirname(DATA_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_file = DATA_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    os.replace(temp_file, DATA_FILE)

    # --------------------------------------------------------
    # 8. Summary
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("GOALRADAR UPDATE COMPLETE")
    print("=" * 60)
    print(f"Today's fixtures: {len(fixtures)}")
    print(f"Filtered fixtures: {len(good_fixtures)}")
    print(f"Today's analyzed picks: {analyzed}")
    print(f"High confidence picks: {high_confidence}")
    print(f"Upcoming leagues: {upcoming_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
