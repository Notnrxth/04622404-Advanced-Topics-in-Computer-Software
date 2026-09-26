from app.football import ALIASES, match_payload, scorer_payload, standing_payload, team_payload


def test_thai_nicknames_cover_all_2026_27_premier_league_clubs():
    nicknames = {
        "AFC Bournemouth": "ลูกเชอร์รี่",
        "Arsenal": "ปืนใหญ่",
        "Aston Villa": "สิงโตผงาด",
        "Brentford": "ผึ้งพิฆาต",
        "Brighton & Hove Albion": "นกนางนวล",
        "Chelsea": "สิงห์บลูส์",
        "Coventry City": "ช้างกระทืบโรง",
        "Crystal Palace": "ปราสาทเรือนแก้ว",
        "Everton": "ทอฟฟี่สีน้ำเงิน",
        "Fulham": "เจ้าสัวน้อย",
        "Hull City": "ไอ้เสือน้อย",
        "Ipswich Town": "ม้าขาว",
        "Leeds United": "ยูงทอง",
        "Liverpool": "หงส์แดง",
        "Manchester City": "เรือใบสีฟ้า",
        "Manchester United": "ปีศาจแดง",
        "Newcastle United": "สาลิกาดง",
        "Nottingham Forest": "เจ้าป่า",
        "Sunderland": "แมวดำ",
        "Tottenham Hotspur": "ไก่เดือยทอง",
    }
    assert set(ALIASES) == set(nicknames)
    for team_id, (name, nickname) in enumerate(nicknames.items(), start=1):
        raw_name = f"{name} FC" if name != "AFC Bournemouth" else name
        payload = team_payload({"id": team_id, "name": raw_name})
        assert nickname in payload["aliases"], name


def test_match_payload_uses_stable_id_bangkok_time_and_contract_status():
    raw = {
        "id": 12345,
        "season": {"startDate": "2026-08-01"},
        "matchday": 5,
        "utcDate": "2026-09-20T11:30:00Z",
        "status": "FINISHED",
        "homeTeam": {"id": 57, "name": "Arsenal FC"},
        "awayTeam": {"id": 61, "name": "Chelsea FC"},
        "score": {
            "fullTime": {"home": 2, "away": 1},
            "halfTime": {"home": 1, "away": 0},
        },
    }
    one = match_payload(raw, "2026-09-21T09:00:00+07:00")
    two = match_payload(raw, "2026-09-21T10:00:00+07:00")
    assert one["match_id"] == two["match_id"]
    assert one["kickoff"] == "2026-09-20T18:30:00+07:00"
    assert one["status"] == "FINISHED"
    assert one["score"]["home"] == 2
    assert one["external_ids"]["football_data"] == 12345


def test_team_and_standings_payloads():
    team = team_payload(
        {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal", "tla": "ARS", "crest": "x"}
    )
    assert "ปืนใหญ่" in team["aliases"]
    raw = {
        "season": {"currentMatchday": 5},
        "standings": [
            {
                "type": "TOTAL",
                "table": [
                    {
                        "position": 1,
                        "team": {"id": 57, "name": "Arsenal FC"},
                        "playedGames": 5,
                        "won": 4,
                        "draw": 1,
                        "lost": 0,
                        "goalsFor": 12,
                        "goalsAgainst": 4,
                        "goalDifference": 8,
                        "points": 13,
                        "form": "WWDWW",
                    }
                ],
            }
        ],
    }
    result = standing_payload(raw, "2026", "2026-09-21T09:00:00+07:00")
    assert result["matchweek"] == 5
    assert result["rows"][0]["points"] == 13


def test_scorers_payload():
    result = scorer_payload(
        {
            "scorers": [
                {
                    "player": {"name": "Example Player"},
                    "team": {"id": 57},
                    "goals": 7,
                    "assists": None,
                }
            ]
        }
    )
    assert result == [{"player": "Example Player", "team_id": 57, "goals": 7, "assists": 0}]
