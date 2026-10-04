"""History parser tests require no network or provider credentials."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import HistoricalMatch, HistoricalStanding, make_database
from app.history import (
    calculate_table,
    historical_document,
    make_documents,
    normalize,
    parse_season,
    relegated,
    resolve,
    season_label,
    table_stats,
    verify_table,
)
from scripts.ingest_history import ROOT, build_dataset, persist


@pytest.mark.parametrize(
    "line",
    [
        "Arsenal FC  2-1 (1-0)  Chelsea FC",
        "15:00 Arsenal FC v Chelsea FC  2-1 (1-0)",
        "15:00 Arsenal FC  2-1 (1-0)  Chelsea FC\n (Player A 20', 30';\n Player B 70')",
    ],
)
def test_parse_all_three_formats_and_ignore_scorers(line):
    text = "# Matches 1\n▪ Regular Season - 5\nSat Sep 20\n" + line
    result = parse_season(text, 2025)
    assert len(result) == 1
    assert result[0]["date"] == "2025-09-20"
    assert result[0]["home_goals"] == 2
    assert result[0]["away"] == "Chelsea FC"


def test_date_year_rollover_and_time_inheritance():
    text = (
        "# Matches 3\n▪ Matchday 20\nTue Dec 30\n15:00 Arsenal 1-0 Chelsea\n"
        "Liverpool 2-0 Everton\nThu Jan 1\nChelsea 0-0 Arsenal"
    )
    matches = parse_season(text, 2025)
    assert [m["date"] for m in matches] == ["2025-12-30", "2025-12-30", "2026-01-01"]
    assert [m["local_time"] for m in matches] == ["15:00", "15:00", None]


def test_covid_season_july_is_the_second_year():
    matches = parse_season("# Matches 1\n▪ Matchday 38\nSun Jul 26\nArsenal 3-2 Watford", 2019)
    assert matches[0]["date"] == "2020-07-26"


def test_fail_loudly_on_bad_count_unknown_line_or_unknown_club():
    with pytest.raises(ValueError, match="expected 380"):
        parse_season("▪ Matchday 1\nSat Aug 16\nArsenal 1-0 Chelsea", 2025)
    with pytest.raises(ValueError, match="unrecognized"):
        parse_season("# Matches 1\nUnexpected team data", 2025)
    with pytest.raises(ValueError, match="Unknown"):
        resolve("New unknown team", {})


def example_data():
    clubs = {
        "arsenal": {"name": "Arsenal FC", "team_id": 57, "aliases": ["Arsenal"]},
        "chelsea": {"name": "Chelsea FC", "team_id": 61, "aliases": ["Chelsea"]},
    }
    matches = normalize(
        parse_season(
            "# Matches 2\n▪ Matchday 1\nSat Aug 16\nArsenal 2-1 Chelsea\n"
            "▪ Matchday 2\nThu Jan 1\nChelsea 0-0 Arsenal",
            2003,
        ),
        clubs,
    )
    return clubs, matches


def test_points_adjustment_and_cross_source_validation():
    _, matches = example_data()
    rows = calculate_table(matches, {"arsenal": -3})
    arsenal = next(row for row in rows if row["club_slug"] == "arsenal")
    assert arsenal["points"] == 1
    verify_table(matches, rows)
    arsenal["goals_for"] += 1
    with pytest.raises(ValueError, match="goals_for"):
        verify_table(matches, rows)


def test_document_metadata_stable_ids_and_credits():
    clubs, matches = example_data()
    docs = make_documents(
        {"2003": matches},
        {"2003": calculate_table(matches)},
        clubs,
        {"2003": "https://example.com/pinned"},
    )
    assert len(docs) == 4
    assert len({d["doc_id"] for d in docs}) == 4
    assert {d["topic"] for d in docs} == {"season_table", "team_season", "head_to_head"}
    for doc in docs:
        assert doc["category"] == "historical"
        assert doc["matchweek"] is doc["date"] is doc["fetched_at"] is None
        assert "Joshua C. Fjelstul, Ph.D." in doc["text"]
        assert "CC-BY-SA 4.0" in doc["text"]
    h2h = next(d for d in docs if d["topic"] == "head_to_head")
    assert h2h["doc_id"] == "hist-h2h-arsenal-chelsea"
    assert h2h["season"] is None
    assert "2 meetings: Arsenal FC won 1, draws 1, Chelsea FC won 0" in h2h["text"]
    biggest_wins = h2h["text"].split("## Biggest wins\n", 1)[1].split("## ", 1)[0]
    assert "Arsenal FC 2-1 Chelsea FC" in biggest_wins
    assert "No Premier League wins for Chelsea FC against Arsenal FC." in biggest_wins
    assert "Chelsea 0-0 Arsenal" not in biggest_wins


@pytest.mark.asyncio
async def test_persist_history_is_idempotent_and_separate(tmp_path):
    _, matches = example_data()
    tables = {"2003": calculate_table(matches)}
    engine, sessions = make_database(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    try:
        for _ in range(2):
            await persist(engine, {"2003": matches}, tables)
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(HistoricalMatch)) == 2
            assert await db.scalar(select(func.count()).select_from(HistoricalStanding)) == 2
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not (ROOT / "data/raw/history/manifest.json").exists(),
    reason="Download pinned historical inputs for full-data verification",
)
def test_all_pinned_seasons_and_all_team_aliases():
    seasons, tables, clubs, docs = build_dataset()
    assert len(seasons) == 34
    assert sum(map(len, seasons.values())) == 13166
    assert len(clubs) == 51
    assert sum(map(len, tables.values())) == 686
    assert len(docs) == 1713
    topics = {t: sum(d["topic"] == t for d in docs) for t in ("club_record", "league_records")}
    assert topics == {"club_record": 51, "league_records": 1}
    records = next(d for d in docs if d["doc_id"] == "hist-records")["text"]
    # Cross-checked against Wikidata (P1346 winners of Q9448 seasons) on 2026-10-04.
    assert (
        "Manchester United FC 13 · Manchester City FC 8 · Chelsea FC 5 · Arsenal FC 4 · "
        "Liverpool FC 2 · Blackburn Rovers FC 1 · Leicester City FC 1.\n"
    ) in records
    assert "7 different clubs have won the Premier League.\n" in records
    assert "most all-time Premier League points? Manchester United FC (2614).\n" in records
    assert "runner-up the most times in the Premier League? Arsenal FC (9).\n" in records
    assert "relegated from the Premier League the most times? Norwich City FC (6).\n" in records
    assert (
        "Which club went a whole Premier League season unbeaten? Arsenal FC 2003/04.\n" in records
    )
    united = next(d for d in docs if d["doc_id"] == "hist-club-manchester-united")["text"]
    assert "Premier League titles: 13 (" in united
    assert "Seasons in the Premier League: 34 of 34. Relegations: 0.\n" in united
    spurs = next(d for d in docs if d["doc_id"] == "hist-club-tottenham")["text"]
    assert "Premier League titles: 0 (never won the Premier League).\n" in spurs
    from app.history import season_scorers

    assert [p["goals"] for p in season_scorers(seasons["2025"])[:3]] == [27, 22, 17]
    assert sum(bool(m.get("goals")) for m in seasons["2025"]) == 353
    season_docs = {d["doc_id"]: d for d in docs if d["topic"] == "season_table"}
    assert "## Top scorers" in season_docs["hist-season-2025"]["text"]
    assert "## Top scorers" not in season_docs["hist-season-2023"]["text"]
    assert "## Top scorers" not in season_docs["hist-season-2024"]["text"]
    assert max(m["date"] for m in seasons["2019"]) == "2020-07-26"
    assert not any(m["date"].startswith("2019-07") for m in seasons["2019"])
    assert sum(d["topic"] == "head_to_head" for d in docs) == 941
    assert (
        next(r for r in tables["1996"] if r["club_slug"] == "middlesbrough")["point_adjustment"]
        == -3
    )
    assert (
        next(r for r in tables["2009"] if r["club_slug"] == "portsmouth")["point_adjustment"] == -9
    )
    assert next(r for r in tables["2023"] if r["club_slug"] == "everton")["point_adjustment"] == -8
    assert (
        next(r for r in tables["2023"] if r["club_slug"] == "nottm-forest")["point_adjustment"]
        == -4
    )
    raw_names = {
        m[k]
        for year in seasons
        for m in parse_season(
            (ROOT / f"data/raw/history/openfootball/{year}.txt").read_text(encoding="utf-8-sig"),
            int(year),
        )
        for k in ("home", "away")
    }
    assert len(raw_names) == 95
    assert {resolve(name, clubs) for name in raw_names} == set(clubs)


def test_scorers_penalties_own_goals_multiple_minutes_and_transfer():
    from app.history import season_scorers

    matches = parse_season(
        "# Matches 2\n▪ Matchday 1\nSat Aug 16\nA 3-2 B\n"
        "(Player One 10', 20'(p), Defender 30'(og); Player Two 40', 90+2')\n"
        "▪ Matchday 2\nSun Aug 17\nB 1-0 A\n(player ONE 50')",
        2025,
    )
    scorers = season_scorers(matches)
    one = next(p for p in scorers if p["player"] == "Player One")
    assert one["goals"] == 3
    assert one["clubs"] == ["A", "B"]
    assert not any(p["player"] == "Defender" for p in scorers)
    assert matches[0]["goals"][1]["penalty"]


def test_incomplete_scorers_are_not_estimated():
    from app.history import season_scorers

    matches = parse_season("# Matches 1\n▪ Matchday 1\nSat Aug 16\nA 1-0 B", 2025)
    with pytest.raises(ValueError, match="Incomplete"):
        season_scorers(matches)


def test_bad_api_scorer_podium_is_rejected(tmp_path):
    import hashlib
    import json

    from app.history import load_scorer_sources

    clubs = {"city": {"aliases": ["Manchester City"]}}
    raw = tmp_path / "scorers"
    raw.mkdir()
    rows = []
    for name, goals in (("E. Haaland", 27), ("Matheus Cunha", 24), ("C. Palmer", 22)):
        rows.append(
            {
                "player": {"name": name},
                "statistics": [
                    {
                        "league": {"id": 39, "season": 2023},
                        "team": {"name": "Manchester City"},
                        "goals": {"total": goals},
                    }
                ],
            }
        )
    path = raw / "2023.json"
    path.write_text(json.dumps({"response": rows}), encoding="utf-8")
    path.with_suffix(".meta.json").write_text(
        json.dumps({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8"
    )
    season = [{"home": "city", "away": "other", "home_goals": 0, "away_goals": 0}]
    sources, validation = load_scorer_sources(tmp_path, clubs, {"2025": season}, {"2025": "pinned"})
    assert "2023" not in sources
    assert validation["2023"]["status"] == "rejected"


def test_current_premier_league_clubs_keep_their_team_id_in_the_archive():
    """Archive documents carry team_ids, so clubs in this season's league need theirs (v1.11)."""
    path = Path(__file__).parents[1] / "data/historical_clubs.json"
    clubs = json.loads(path.read_text("utf-8"))
    current = {"west-ham": 563, "wolves": 76, "burnley": 328, "arsenal": 57, "sunderland": 71}
    assert {slug: clubs[slug]["team_id"] for slug in current} == current


def test_season_label_handles_the_century_rollover():
    assert season_label("2004") == "2004/05"
    assert season_label("1999") == "1999/00"


def test_relegated_sorts_rows_and_drops_four_in_1994():
    rows = [{"club_slug": f"c{p}", "position": p} for p in (3, 1, 6, 2, 5, 4)]
    assert [r["position"] for r in relegated("1994", rows)] == [3, 4, 5, 6]
    assert [r["position"] for r in relegated("1995", rows)] == [4, 5, 6]


def test_table_stats_shows_an_adjustment_only_when_there_is_one():
    row = {
        "played": 38,
        "wins": 10,
        "draws": 5,
        "losses": 23,
        "goals_for": 30,
        "goals_against": 60,
        "goal_difference": -30,
        "points": 26,
    }
    assert table_stats(row) == "P38 W10 D5 L23 GF30 GA60 GD-30 Pts26"
    assert table_stats({**row, "point_adjustment": 0}) == "P38 W10 D5 L23 GF30 GA60 GD-30 Pts26"
    assert table_stats({**row, "point_adjustment": -9}).endswith("Pts26; point adjustment -9")


def test_historical_document_adds_credit_and_known_team_ids():
    clubs = {
        "arsenal": {"name": "Arsenal FC", "team_id": 57},
        "wimbledon": {"name": "Wimbledon FC", "team_id": None},
    }
    doc = historical_document(
        clubs,
        "hist-x",
        "T",
        "body",
        "season_table",
        "2003",
        ["wimbledon", "arsenal"],
        "openfootball",
        "https://example.com",
    )
    assert doc["team_ids"] == [57]
    assert doc["text"].startswith("body\n## Sources and license\n")
    assert (doc["category"], doc["matchweek"], doc["date"], doc["fetched_at"]) == (
        "historical",
        None,
        None,
        None,
    )
