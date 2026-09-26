"""History parser tests require no network or provider credentials."""

import pytest
from sqlalchemy import func, select

from app.db import HistoricalMatch, HistoricalStanding, make_database
from app.history import (
    calculate_table,
    make_documents,
    normalize,
    parse_season,
    resolve,
    verify_table,
)
from scripts.ingest_history import ROOT, build_dataset, persist


@pytest.mark.parametrize(
    "line",
    [
        "Arsenal FC  2-1 (1-0)  Chelsea FC",
        "15:00 Arsenal FC v Chelsea FC  2-1 (1-0)",
        "15:00 Arsenal FC  2-1 (1-0)  Chelsea FC\n (Player A 20';\n Player B 70')",
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
    assert len(docs) == 1661
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
