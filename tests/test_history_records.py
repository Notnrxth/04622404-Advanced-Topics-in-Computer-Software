"""Club records and league honours computed from final tables (no network)."""

import re

import pytest

from app import history_records
from app.history_records import make_record_documents, ordinal

# Copied from 05's app/kb/documents.py (CONTRACT §6 v1.13) so 07 cannot drift from it.
HISTORICAL_ID = re.compile(
    r"hist-(?:season-\d{4}|team-\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*|h2h-[a-z0-9]+(?:-[a-z0-9]+)*"
    r"|club-[a-z0-9]+(?:-[a-z0-9]+)*|records)"
)

CLUBS = {
    "arsenal": {"name": "Arsenal FC", "team_id": 57},
    "chelsea": {"name": "Chelsea FC", "team_id": 61},
    "everton": {"name": "Everton FC", "team_id": 62},
    "leeds-united": {"name": "Leeds United FC", "team_id": None},
    "fulham": {"name": "Fulham FC", "team_id": 63},
    "wimbledon": {"name": "Wimbledon FC", "team_id": None},
    "bolton-wanderers": {"name": "Bolton Wanderers FC", "team_id": None},
    "ipswich-town": {"name": "Ipswich Town FC", "team_id": 349},
    "derby-county": {"name": "Derby County FC", "team_id": None},
}


def table(order, adjustments=None):
    """Final table in finishing order: n-i wins, i-1 losses, no draws."""
    n, rows = len(order), []
    for i, slug in enumerate(order, 1):
        adjustment = (adjustments or {}).get(slug, 0)
        gf, ga = 10 - i, i
        rows.append(
            {
                "club_slug": slug,
                "position": i,
                "played": n - 1,
                "wins": n - i,
                "draws": 0,
                "losses": i - 1,
                "goals_for": gf,
                "goals_against": ga,
                "goal_difference": gf - ga,
                "points": 3 * (n - i) + adjustment,
                "point_adjustment": adjustment,
            }
        )
    return rows


TABLES = {
    "2000": table(["arsenal", "chelsea", "everton", "leeds-united", "fulham", "wimbledon"]),
    "2001": table(
        ["chelsea", "arsenal", "everton", "bolton-wanderers", "ipswich-town", "derby-county"]
    ),
    "2002": table(
        ["arsenal", "everton", "chelsea", "leeds-united", "fulham", "bolton-wanderers"],
        {"leeds-united": -3},
    ),
}


def docs():
    return {d["doc_id"]: d for d in make_record_documents(TABLES, CLUBS)}


def body(doc):
    return doc["text"].split("\n## Sources and license\n", 1)[0]


def test_one_document_per_club_then_the_records_document():
    documents = make_record_documents(TABLES, CLUBS)
    assert [d["doc_id"] for d in documents] == [
        *(f"hist-club-{slug}" for slug in sorted(CLUBS)),
        "hist-records",
    ]
    assert all(HISTORICAL_ID.fullmatch(d["doc_id"]) for d in documents)


def test_metadata_and_license_follow_the_archive():
    for doc in make_record_documents(TABLES, CLUBS):
        assert doc["category"] == "historical"
        assert doc["origin"] == "fjelstul"
        assert doc["url"] == "https://github.com/jfjelstul/englishfootball"
        assert doc["season"] is doc["matchweek"] is doc["date"] is doc["fetched_at"] is None
        assert "Joshua C. Fjelstul, Ph.D." in doc["text"]
        assert body(doc).startswith(
            "Coverage: Premier League seasons 2000/01 to 2002/03 only. Top-flight league titles "
            "won before the Premier League began in 1992 (First Division) are not included.\n"
        )
    d = docs()
    assert d["hist-club-arsenal"]["topic"] == "club_record"
    assert d["hist-club-arsenal"]["title"] == "Arsenal FC — Premier League record 2000/01–2002/03"
    assert d["hist-club-arsenal"]["team_ids"] == [57]
    assert d["hist-club-wimbledon"]["team_ids"] == []
    assert d["hist-records"]["topic"] == "league_records"
    assert d["hist-records"]["title"] == (
        "Premier League honours and all-time records 2000/01–2002/03"
    )
    assert d["hist-records"]["team_ids"] == [57, 61, 62, 63, 349]


def test_club_titles_runners_up_seasons_and_finishes():
    text = body(docs()["hist-club-arsenal"])
    assert "Premier League titles: 2 (2000/01, 2002/03).\n" in text
    assert "Runners-up: 1 (2001/02).\n" in text
    assert "Seasons in the Premier League: 3 of 3. Relegations: 0.\n" in text
    assert "Best finish: 1st (2 times). Worst finish: 2nd (2001/02).\n" in text
    assert "All-time Premier League record: P15 W14 D0 L1 GF26 GA4 GD+22 Pts42.\n" in text
    assert "## Finishes by season 2000/01–2002/03\n2000/01: 1st, 15 pts\n" in text


def test_club_without_titles_says_never_won():
    text = body(docs()["hist-club-everton"])
    assert "Premier League titles: 0 (never won the Premier League).\n" in text
    assert "Runners-up: 1 (2002/03).\n" in text
    derby = body(docs()["hist-club-derby-county"])
    assert "Runners-up: 0.\n" in derby
    assert "()" not in derby
    assert "Seasons in the Premier League: 1 of 3. Relegations: 1 (2001/02).\n" in derby
    assert "Best finish: 6th (1 time). Worst finish: 6th (2001/02).\n" in derby


def test_point_adjustment_is_kept_in_totals_and_finishes():
    text = body(docs()["hist-club-leeds-united"])
    assert "Relegations: 2 (2000/01, 2002/03).\n" in text
    assert "2002/03: 4th, 3 pts (point adjustment -3)\n" in text
    assert "All-time Premier League record: P10 W4 D0 L6 GF12 GA8 GD+4 Pts9.\n" in text


def test_finishes_split_into_groups(monkeypatch):
    monkeypatch.setattr(history_records, "GROUP", 2)
    text = body(docs()["hist-club-arsenal"])
    assert "## Finishes by season 2000/01–2001/02\n" in text
    assert "## Finishes by season 2002/03–2002/03\n" in text


def test_records_titles_champions_and_ever_present():
    text = body(docs()["hist-records"])
    assert "Arsenal FC 2 · Chelsea FC 1.\n" in text
    assert "2 different clubs have won the Premier League.\n" in text
    assert (
        "## Champions and runners-up 2000/01–2002/03\n"
        "2000/01: Arsenal FC (runners-up Chelsea FC)\n"
        "2001/02: Chelsea FC (runners-up Arsenal FC)\n"
        "2002/03: Arsenal FC (runners-up Everton FC)\n"
    ) in text
    assert (
        "## Ever-present clubs\nมี 3 ทีมที่อยู่พรีเมียร์ลีกครบทุกฤดูกาล (3 ฤดูกาล) และไม่เคยตกชั้น\n"
        "3 clubs have played in all 3 Premier League seasons: "
        "Arsenal FC, Chelsea FC, Everton FC.\n"
    ) in text


def test_records_all_time_table_breaks_ties_by_gd_gf_then_name():
    table_text = body(docs()["hist-records"]).split("## All-time table: positions 1-9\n", 1)[1]
    rows = [line for line in table_text.splitlines() if line[:1].isdigit()]
    names = [line.split(". ", 1)[1].split(":", 1)[0] for line in rows]
    assert names == [
        "Arsenal FC",
        "Chelsea FC",
        "Everton FC",
        "Leeds United FC",
        "Bolton Wanderers FC",
        "Fulham FC",
        "Ipswich Town FC",
        "Derby County FC",
        "Wimbledon FC",
    ]
    assert table_text.startswith(
        "ตารางคะแนนรวมตลอดกาลของพรีเมียร์ลีก ทีมที่เก็บแต้มรวมมากที่สุดคือ Arsenal FC (42 แต้ม)\n"
        "1. Arsenal FC: P15 W14 D0 L1 GF26 GA4 GD+22 Pts42\n"
    )


def test_records_grammar_for_a_single_club():
    tables = {
        "2000": table(["arsenal", "chelsea", "everton", "leeds-united"]),
        "2001": table(["arsenal", "fulham", "wimbledon", "derby-county"]),
    }
    text = body(make_record_documents(tables, CLUBS)[-1])
    assert "1 different club has won the Premier League.\n" in text
    assert "1 club has played in all 2 Premier League seasons: Arsenal FC.\n" in text


@pytest.mark.parametrize(
    ("n", "label"),
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
    ],
)
def test_ordinal(n, label):
    assert ordinal(n) == label


def test_club_summary_sentence_in_english_only():
    # Thai text here outranked head-to-head documents for Thai questions (eval 2026-10-04).
    d = docs()
    arsenal = body(d["hist-club-arsenal"])
    assert "Arsenal FC have won the Premier League title 2 times.\nPremier League titles: 2" in (
        arsenal
    )
    assert "Chelsea FC have won the Premier League title once.\n" in body(d["hist-club-chelsea"])
    assert "Everton FC have never won the Premier League title.\n" in body(d["hist-club-everton"])
    assert not any(
        "฀" <= ch <= "๿"
        for doc in d.values()
        if doc["topic"] == "club_record"
        for ch in doc["text"]
    )


def test_records_summary_sentences_in_english_and_thai():
    text = body(docs()["hist-records"])
    assert (
        "## Titles by club\nMost Premier League titles: Arsenal FC (2).\n"
        "ทีมที่ได้แชมป์พรีเมียร์ลีกมากที่สุดคือ Arsenal FC (2 สมัย) "
        "มีทั้งหมด 2 ทีมที่เคยได้แชมป์พรีเมียร์ลีก\nArsenal FC 2 · Chelsea FC 1.\n"
    ) in text


def test_records_summary_lists_every_club_tied_on_most_titles():
    tables = {
        "2000": table(["arsenal", "everton", "leeds-united", "fulham"]),
        "2001": table(["chelsea", "wimbledon", "derby-county", "bolton-wanderers"]),
    }
    text = body(make_record_documents(tables, CLUBS)[-1])
    assert "Most Premier League titles: Arsenal FC, Chelsea FC (1).\n" in text
    assert "ทีมที่ได้แชมป์พรีเมียร์ลีกมากที่สุดคือ Arsenal FC, Chelsea FC (1 สมัย)" in text
    assert "## Ever-present clubs\nไม่มีทีมใดอยู่พรีเมียร์ลีกครบทุกฤดูกาล\n" in text
