import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode

API_KEY = os.environ.get("API_FOOTBALL_KEY")

if not API_KEY:
    print("Missing API_FOOTBALL_KEY secret", file=sys.stderr)
    sys.exit(1)

BASE = "https://v3.football.api-sports.io"

# --------------------------------------------------
# DATES
# --------------------------------------------------

NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
UPCOMING_FROM = TODAY
UPCOMING_TO = (NOW + timedelta(days=14)).strftime("%Y-%m-%d")


# --------------------------------------------------
# API REQUEST
# --------------------------------------------------

def get(path, params=None):
    if params:
        query = urlencode(params)
        url = BASE + path + "?" + query
    else:
        url = BASE + path

    req = Request(
        url,
        headers={
            "x-apisports-key": API_KEY,
            "Accept": "application/json",
        },
    )

    with urlopen(req, timeout=30) as response:
        data = json.load(response)

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    return data.get("response", [])


# --------------------------------------------------
# GOALRADAR'S FIVE MAIN LEAGUES
# --------------------------------------------------

MAIN_LEAGUES = {
    39: "EPL",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "UCL",
}


# --------------------------------------------------
# OTHER LEAGUES FOR DAILY PICKS
# --------------------------------------------------

PRIORITY_LEAGUES = {
    39: "EPL",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    2: "UCL",
    61: "Ligue 1",
    88: "Eredivisie",
    94: "Primeira Liga",
    203: "Turkish Super Lig",
    144: "Belgian Pro League",
    71: "Brazil Serie A",
    128: "Argentina Liga Profesional",
}


# --------------------------------------------------
# GET TODAY'S FIXTURES
# --------------------------------------------------

fixtures = get(
    "/fixtures",
    {
        "date": TODAY
    }
)


# --------------------------------------------------
# SCORE FIXTURES FOR DAILY PICKS
# --------------------------------------------------

def score_fixture(fixture):
    league_id = fixture.get("league", {}).get("id")
    league_name = fixture.get("league", {}).get(
        "name", ""
    ).lower()

    if league_id in PRIORITY_LEAGUES:
        return 1000 - list(PRIORITY_LEAGUES).index(
            league_id
        )

    if any(word in league_name for word in [
        "world cup",
        "euro",
        "nations league",
        "africa cup",
        "copa"
    ]):
        return 800

    if any(word in league_name for word in [
        "premier",
        "division",
        "liga",
        "serie",
        "super league",
        "championship"
    ]):
        return 600

    if any(word in league_name for word in [
        "women",
        "u19",
        "u20",
        "u21",
        "u23",
        "youth",
        "reserve",
        "friendly"
    ]):
        return 100

    return 300


# --------------------------------------------------
# SELECT BEST MATCHES FOR TODAY'S PICKS
# --------------------------------------------------

selected = sorted(
    fixtures,
    key=lambda fixture: (
        -score_fixture(fixture),
        fixture.get("fixture", {}).get(
            "timestamp", 0
        )
    )
)[:12]


# --------------------------------------------------
# GENERATE PREDICTIONS
# --------------------------------------------------

picks = []

for fixture in selected:

    fixture_id = fixture["fixture"]["id"]

    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]

    league_id = fixture["league"]["id"]

    league = PRIORITY_LEAGUES.get(
        league_id,
        fixture["league"].get(
            "name",
            "Football"
        )
    )

    pick = "Analysis pending"
    confidence = 0
    prediction_type = "Match"

    try:

        prediction = get(
            "/predictions",
            {
                "fixture": fixture_id
            }
        )

        if prediction:

            prediction_data = prediction[0].get(
                "predictions",
                {}
            )

            winner = prediction_data.get(
                "winner"
            ) or {}

            winner_name = winner.get("name")

            probabilities = prediction_data.get(
                "percent"
            ) or {}

            if winner_name:

                pick = winner_name + " Win"
                prediction_type = "1X2"

                if winner_name == home:
                    key = "home"

                elif winner_name == away:
                    key = "away"

                else:
                    key = "draw"

                raw = str(
                    probabilities.get(
                        key,
                        "0"
                    )
                ).replace("%", "")

                try:
                    confidence = int(
                        float(raw)
                    )
                except:
                    confidence = 0

            if not confidence:
                confidence = 60

    except Exception as error:

        print(
            f"Prediction failed for fixture "
            f"{fixture_id}: {error}",
            file=sys.stderr
        )

    picks.append({
        "league": league,
        "home": home,
        "away": away,
        "pick": pick,
        "type": prediction_type,
        "confidence": confidence,
        "fixture_id": fixture_id,
        "kickoff": fixture["fixture"]["date"]
    })


# --------------------------------------------------
# GET UPCOMING MATCHES FOR THE FIVE MAIN LEAGUES
# --------------------------------------------------

upcoming = {}

for league_id, league_name in MAIN_LEAGUES.items():

    print(
        f"Getting upcoming {league_name} fixtures..."
    )

    try:

        league_fixtures = get(
            "/fixtures",
            {
                "league": league_id,
                "season": 2026,
                "timezone": "Africa/Accra"
            }
        )

        league_matches = []

        for fixture in league_fixtures:

            fixture_info = fixture.get(
                "fixture",
                {}
            )

            status = fixture_info.get(
                "status",
                {}
            ).get(
                "short",
                ""
            )

            # Only upcoming/not-started fixtures
            if status not in [
                "NS",
                "TBD"
            ]:
                continue

            timestamp = fixture_info.get(
                "timestamp",
                0
            )

            # Don't include matches already in the past
            if timestamp and timestamp < NOW.timestamp():
                continue

            teams = fixture.get(
                "teams",
                {}
            )

            home_team = teams.get(
                "home",
                {}
            ).get(
                "name",
                "Home"
            )

            away_team = teams.get(
                "away",
                {}
            ).get(
                "name",
                "Away"
            )

            venue = fixture.get(
                "fixture",
                {}
            ).get(
                "venue",
                {}
            )

            league_info = fixture.get(
                "league",
                {}
            )

            league_matches.append({
                "fixture_id": fixture_info.get(
                    "id"
                ),

                "home": home_team,

                "away": away_team,

                "kickoff": fixture_info.get(
                    "date"
                ),

                "timestamp": timestamp,

                "venue": venue.get(
                    "name"
                ) or "Venue TBC",

                "city": venue.get(
                    "city"
                ),

                "round": league_info.get(
                    "round"
                ),

                "league": league_name,

                "league_id": league_id
            })

        # Sort by kickoff
        league_matches.sort(
            key=lambda x: x.get(
                "timestamp",
                0
            )
        )

        # Keep the next 20 matches per league
        upcoming[league_name] = league_matches[:20]

        print(
            f"{league_name}: "
            f"{len(upcoming[league_name])} "
            f"upcoming matches"
        )

    except Exception as error:

        print(
            f"Failed to get {league_name}: "
            f"{error}",
            file=sys.stderr
        )

        upcoming[league_name] = []


# --------------------------------------------------
# HIGH-CONFIDENCE COUNT
# --------------------------------------------------
# Build upcoming matches for the main leagues
upcoming = {
    "EPL": [],
    "La Liga": [],
    "Serie A": [],
    "Bundesliga": [],
    "Ligue 1": [],
    "UCL": []
}

NOW_TS = datetime.now(timezone.utc).timestamp()

for league_id, league_name in {
    39: "EPL",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "UCL"
}.items():

    try:
        league_fixtures = get(
            f"/fixtures?league={league_id}&season=2026&timezone=Africa/Accra"
        )

        future_matches = [
            match for match in league_fixtures
            if match.get("fixture", {}).get("timestamp", 0) > NOW_TS
        ]

        future_matches.sort(
            key=lambda match: match.get("fixture", {}).get("timestamp", 0)
        )

        for match in future_matches[:10]:
            upcoming[league_name].append({
                "league": league_name,
                "home": match["teams"]["home"]["name"],
                "away": match["teams"]["away"]["name"],
                "fixture_id": match["fixture"]["id"],
                "kickoff": match["fixture"]["date"],
                "venue": match.get("fixture", {}).get("venue", {}).get("name"),
                "city": match.get("fixture", {}).get("venue", {}).get("city"),
                "round": match.get("league", {}).get("round")
            })

    except Exception as error:
        print(
            f"Upcoming fixtures failed for {league_name}: {error}",
            file=sys.stderr
        )
high_confidence = sum(
    1
    for item in picks
    if item["confidence"] >= 75
)


# --------------------------------------------------
# FINAL GOALRADAR DATA
# --------------------------------------------------

output = {

    "updated_at":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "date":
        datetime.now(
            timezone.utc
        ).strftime(
            "%d %b %Y"
        ).upper(),

    "stats": {

        "matches_today":
            len(fixtures),

        "analyzed":
            len(picks),

        "high_confidence":
            high_confidence,

        "upcoming_leagues":
            len([
                league
                for league, matches
                in upcoming.items()
                if matches
            ])
    },

    # Today's predictions
    "picks": picks,

    # Upcoming fixtures for league buttons
    "upcoming": upcoming
}


# --------------------------------------------------
# SAVE JSON
# --------------------------------------------------

os.makedirs(
    "data",
    exist_ok=True
)

with open(
    "data/goalradar.json",
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        output,
        file,
        ensure_ascii=False,
        indent=2
    )


# --------------------------------------------------
# SUCCESS MESSAGE
# --------------------------------------------------

total_upcoming = sum(
    len(matches)
    for matches in upcoming.values()
)

print(
    f"GoalRadar updated for {TODAY}"
)

print(
    f"Today's fixtures: {len(fixtures)}"
)

print(
    f"Today's analyzed picks: {len(picks)}"
)

print(
    f"Upcoming main-league matches: "
    f"{total_upcoming}"
)
