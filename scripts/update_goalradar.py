import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode

API_KEY = os.environ.get("API_FOOTBALL_KEY")

if not API_KEY:
    print("Missing API_FOOTBALL_KEY secret", file=sys.stderr)
    sys.exit(1)

BASE = "https://v3.football.api-sports.io"

NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
NOW_TS = NOW.timestamp()


# ==================================================
# API REQUEST
# ==================================================

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


# ==================================================
# GOALRADAR MAIN LEAGUES
# ==================================================

MAIN_LEAGUES = {
    39: "EPL",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "UCL",
}


# ==================================================
# OTHER LEAGUES FOR DAILY PICKS
# ==================================================

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


# ==================================================
# FIND CURRENT SEASON FOR A LEAGUE
# ==================================================

def get_current_season(league_id):

    seasons = get(
        "/leagues",
        {
            "id": league_id
        }
    )

    if not seasons:
        raise RuntimeError(
            f"No league information returned for {league_id}"
        )

    league_data = seasons[0]

    season_list = league_data.get(
        "seasons",
        []
    )

    # Prefer season marked current
    for season in season_list:
        if season.get("current") is True:
            return season.get("year")

    # Fallback: choose latest season
    valid_years = [
        season.get("year")
        for season in season_list
        if season.get("year")
    ]

    if valid_years:
        return max(valid_years)

    raise RuntimeError(
        f"No season found for league {league_id}"
    )


# ==================================================
# GET TODAY'S FIXTURES
# ==================================================

fixtures = get(
    "/fixtures",
    {
        "date": TODAY
    }
)


# ==================================================
# SCORE FIXTURES
# ==================================================

def score_fixture(fixture):

    league_id = fixture.get(
        "league",
        {}
    ).get("id")

    league_name = fixture.get(
        "league",
        {}
    ).get(
        "name",
        ""
    ).lower()

    # Main priority leagues
    if league_id in PRIORITY_LEAGUES:

        return (
            1000
            - list(PRIORITY_LEAGUES).index(
                league_id
            )
        )

    # Major international competitions
    if any(
        word in league_name
        for word in [
            "world cup",
            "euro",
            "nations league",
            "africa cup",
            "copa"
        ]
    ):
        return 800

    # General professional competitions
    if any(
        word in league_name
        for word in [
            "premier",
            "division",
            "liga",
            "serie",
            "super league",
            "championship"
        ]
    ):
        return 600

    # Avoid youth/women/friendly games
    if any(
        word in league_name
        for word in [
            "women",
            "u19",
            "u20",
            "u21",
            "u23",
            "youth",
            "reserve",
            "friendly"
        ]
    ):
        return 100

    return 300


# ==================================================
# SELECT TODAY'S BEST FIXTURES
# ==================================================

selected = sorted(
    fixtures,
    key=lambda fixture: (
        -score_fixture(fixture),
        fixture.get(
            "fixture",
            {}
        ).get(
            "timestamp",
            0
        )
    )
)[:12]


# ==================================================
# GENERATE DAILY PREDICTIONS
# ==================================================

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

            winner_name = winner.get(
                "name"
            )

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
                ).replace(
                    "%",
                    ""
                )

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


# ==================================================
# UPCOMING FIXTURES
# ==================================================

upcoming = {}

for league_id, league_name in MAIN_LEAGUES.items():

    print(
        f"Getting upcoming {league_name} fixtures..."
    )

    upcoming[league_name] = []

    try:

        # ------------------------------------------
        # Find the active season automatically
        # ------------------------------------------

        season = get_current_season(
            league_id
        )

        print(
            f"{league_name} current season: "
            f"{season}"
        )

        # ------------------------------------------
        # Get fixtures for that season
        # ------------------------------------------

        league_fixtures = get(
            "/fixtures",
            {
                "league": league_id,
                "season": season,
                "timezone": "Africa/Accra"
            }
        )

        future_matches = []

        for fixture in league_fixtures:

            fixture_info = fixture.get(
                "fixture",
                {}
            )

            timestamp = fixture_info.get(
                "timestamp",
                0
            )

            # Must have a valid future timestamp
            if not timestamp:
                continue

            if timestamp <= NOW_TS:
                continue

            # --------------------------------------
            # Only not-started matches
            # --------------------------------------

            status = fixture_info.get(
                "status",
                {}
            ).get(
                "short",
                ""
            )

            if status not in [
                "NS",
                "TBD"
            ]:
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

            venue = fixture_info.get(
                "venue",
                {}
            )

            league_info = fixture.get(
                "league",
                {}
            )

            future_matches.append({

                "league": league_name,

                "home": home_team,

                "away": away_team,

                "fixture_id": fixture_info.get(
                    "id"
                ),

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

                "league_id": league_id
            })

        # ------------------------------------------
        # Sort chronologically
        # ------------------------------------------

        future_matches.sort(
            key=lambda match:
            match.get(
                "timestamp",
                0
            )
        )

        # ------------------------------------------
        # Keep next 10
        # ------------------------------------------

        upcoming[league_name] = (
            future_matches[:10]
        )

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


# ==================================================
# HIGH CONFIDENCE
# ==================================================

high_confidence = sum(

    1

    for item in picks

    if item["confidence"] >= 75
)


# ==================================================
# UPCOMING LEAGUE COUNT
# ==================================================

upcoming_league_count = sum(

    1

    for matches in upcoming.values()

    if matches
)


# ==================================================
# FINAL GOALRADAR DATA
# ==================================================

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
            upcoming_league_count
    },

    "picks":
        picks,

    "upcoming":
        upcoming
}


# ==================================================
# SAVE JSON
# ==================================================

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


# ==================================================
# SUCCESS MESSAGE
# ==================================================

total_upcoming = sum(
    len(matches)
    for matches in upcoming.values()
)

print("")
print("======================================")
print("GOALRADAR UPDATE COMPLETE")
print("======================================")
print(
    f"Today's fixtures: {len(fixtures)}"
)
print(
    f"Today's analyzed picks: {len(picks)}"
)
print(
    f"Upcoming leagues: {upcoming_league_count}"
)
print(
    f"Upcoming matches: {total_upcoming}"
)
print("======================================")
