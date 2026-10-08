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

fixtures = get(f"/fixtures?date={TODAY}")

allowed = {
    "EPL": 39,
    "La Liga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "UCL": 2,
}
league_by_id = {value: key for key, value in allowed.items()}

selected = [
    fixture
    for fixture in fixtures
    if fixture.get("league", {}).get("id") in league_by_id
]

selected.sort(
    key=lambda item: item.get("fixture", {}).get("timestamp", 0)
)
selected = selected[:12]

picks = []

for fixture in selected:
    fixture_id = fixture["fixture"]["id"]
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    league = league_by_id[fixture["league"]["id"]]

    pick = "Analysis pending"
    confidence = 0
    prediction_type = "Match"

    try:
        prediction = get(f"/predictions?fixture={fixture_id}")

        if prediction:
            prediction_data = prediction[0].get("predictions", {})
            winner = prediction_data.get("winner") or {}
            winner_name = winner.get("name")
            probabilities = prediction_data.get("percent") or {}

            if winner_name:
                pick = winner_name + " Win"
                prediction_type = "1X2"

                if winner_name == home:
                    key = "home"
                elif winner_name == away:
                    key = "away"
                else:
                    key = "draw"

                raw = str(probabilities.get(key, "0")).replace("%", "")
                confidence = int(float(raw))

            if not confidence:
                confidence = 60

    except Exception as error:
        print(
            f"Prediction failed for fixture {fixture_id}: {error}",
            file=sys.stderr,
        )

    picks.append({
        "league": league,
        "home": home,
        "away": away,
        "pick": pick,
        "type": prediction_type,
        "confidence": confidence,
        "fixture_id": fixture_id,
        "kickoff": fixture["fixture"]["date"],
    })

high_confidence = sum(
    1 for item in picks if item["confidence"] >= 75
)

output = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "date": datetime.now(timezone.utc).strftime("%d %b %Y").upper(),
    "stats": {
        "matches_today": len(fixtures),
        "analyzed": len(picks),
        "high_confidence": high_confidence,
    },
    "picks": picks,
}

os.makedirs("data", exist_ok=True)

with open("data/goalradar.json", "w", encoding="utf-8") as file:
    json.dump(output, file, ensure_ascii=False, indent=2)

print(
    f"Updated GoalRadar for {TODAY}: "
    f"{len(fixtures)} fixtures, {len(picks)} analyzed."
)
