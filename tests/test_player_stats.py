from app.football import scorer_payload
from app.service import FootballService

FETCHED_AT = "2026-09-30T10:00:00+07:00"


def standings_text(scorers: list[dict]) -> str:
    standing = {
        "matchweek": 6,
        "snapshot_type": "live",
        "rows": [
            {
                "position": 1,
                "team_id": 57,
                "name": "Arsenal FC",
                "points": 13,
                "played": 6,
                "goal_difference": 9,
            }
        ],
    }
    documents = FootballService._documents([], standing, "2026", FETCHED_AT, scorers)
    return next(d for d in documents if d["category"] == "standings")["text"]


def test_unreported_assists_stay_none():
    rows = scorer_payload(
        {"scorers": [{"player": {"name": "A"}, "team": {"id": 57}, "goals": 3, "assists": None}]}
    )
    assert rows[0]["assists"] is None


def test_standings_document_says_not_reported_instead_of_zero():
    text = standings_text(
        [
            {"player": "Erling Haaland", "team_id": 65, "goals": 5, "assists": None},
            {"player": "Bukayo Saka", "team_id": 57, "goals": 3, "assists": 2},
        ]
    )
    assert "1. Erling Haaland (65): 5 goals, assists not reported." in text
    assert "2. Bukayo Saka (Arsenal FC): 3 goals, 2 assists." in text
    assert "0 assists" not in text
    assert "None" not in text
