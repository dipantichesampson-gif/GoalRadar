import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen

API_KEY = os.environ.get("API_FOOTBALL_KEY")

if not API_KEY:
    print("Missing API_FOOTBALL_KEY secret", file=sys.stderr)
    sys.exit(1)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
BASE = "https://v3.football.api-sports.io"


def get(path):
    req = Request(
        BASE + path,
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


# Main leagues get priority.
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

fixtures = get(f"/fixtures?date={TODAY}")


def score_fixture(fixture):
    league_id = fixture.get("league", {}).get("id")
    league_name = fixture.get("league", {}).get("name", "").lower()

    if league_id in PRIORITY_LEAGUES:
        return 1000 - list(PRIORITY_LEAGUES).index(league_id)

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


# Automatically choose the best available matches.
selected = sorted(
    fixtures,
    key=lambda fixture: (
        -score_fixture(fixture),
        fixture.get("fixture", {}).get("timestamp", 0)
    )
)[:12]


picks = []

for fixture in selected:

    fixture_id = fixture["fixture"]["id"]

    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]

    league_id = fixture["league"]["id"]
    league = PRIORITY_LEAGUES.get(
        league_id,
        fixture["league"].get("name", "Football")
    )

    pick = "Analysis pending"
    confidence = 0
    prediction_type = "Match"

    try:

        prediction = get(
            f"/predictions?fixture={fixture_id}"
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
                    probabilities.get(key, "0")
                ).replace("%", "")

                try:
                    confidence = int(float(raw))
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


high_confidence = sum(
    1
    for item in picks
    if item["confidence"] >= 75
)


output = {
    "updated_at":
        datetime.now(timezone.utc).isoformat(),

    "date":
        datetime.now(timezone.utc).strftime(
            "%d %b %Y"
        ).upper(),

    "stats": {
        "matches_today": len(fixtures),
        "analyzed": len(picks),
        "high_confidence": high_confidence
    },

    "picks": picks
}


os.makedirs("data", exist_ok=True)

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


print(
    f"Updated GoalRadar for {TODAY}: "
    f"{len(fixtures)} fixtures, "
    f"{len(picks)} analyzed."
)
