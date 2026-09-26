"""Pinned Football.TXT parsing and historical table verification (no live APIs)."""

import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

MONTHS = {
    name: n
    for n, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
DATE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$"
)
ROUND = re.compile(r"^▪\s*(?:Matchday\s+|Regular Season\s*-\s*)(\d+)")
SCORE = re.compile(r"^(.*?)\s+(\d+)-(\d+)(?:\s+\(\d+-\d+\))?\s+(.+?)\s*$")
VERSUS = re.compile(r"^(.+?)\s+v\s+(.+?)\s+(\d+)-(\d+)(?:\s+\(\d+-\d+\))?\s*$")
TIME = re.compile(r"^(\d{1,2}:\d{2})\s+")
FIELDS = (
    "played",
    "wins",
    "draws",
    "losses",
    "goals_for",
    "goals_against",
    "goal_difference",
    "points",
)


def parse_season(text: str, year: int) -> list[dict]:
    matches, day, week, clock = [], None, None, None
    scorer_block = False
    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if scorer_block or line.startswith("("):
            scorer_block = not line.endswith(")")
            continue
        if not line or line.startswith(("#", "=", "(", ")")):
            continue
        round_match = ROUND.match(line)
        if round_match:
            week = int(round_match[1])
            continue
        date_match = DATE.match(line)
        if date_match:
            month = MONTHS[date_match[1]]
            # The 2019/20 COVID-delayed season continued into July 2020.
            date_year = int(date_match[3]) if date_match[3] else year + (month < 8)
            if date_year not in (year, year + 1):
                raise ValueError(f"{year}:{number}: date outside season")
            day = date(
                date_year,
                month,
                int(date_match[2]),
            ).isoformat()
            clock = None
            continue
        time_match = TIME.match(line)
        if time_match:
            clock = time_match[1]
            line = line[time_match.end() :]
        versus = VERSUS.match(line)
        standard = SCORE.match(line)
        if versus:
            home, away, hg, ag = versus.groups()
        elif standard:
            home, hg, ag, away = standard.groups()
        else:
            raise ValueError(f"{year}:{number}: unrecognized line: {line}")
        if day is None or week is None:
            raise ValueError(f"{year}:{number}: match has no date/round")
        matches.append(
            {
                "season": str(year),
                "matchweek": week,
                "date": day,
                "local_time": clock,
                "home": home.strip(),
                "away": away.strip(),
                "home_goals": int(hg),
                "away_goals": int(ag),
            }
        )
    if scorer_block:
        raise ValueError(f"{year}: unterminated scorer block")
    header = re.search(r"^# Matches\s+(\d+)", text, re.M)
    expected = int(header[1]) if header else (462 if year <= 1994 else 380)
    if len(matches) != expected:
        raise ValueError(f"{year}: parsed {len(matches)} matches; expected {expected}")
    pairs = [(m["home"], m["away"]) for m in matches]
    if len(pairs) != len(set(pairs)):
        raise ValueError(f"{year}: duplicate home/away pairing")
    return matches


def resolve(name: str, clubs: dict) -> str:
    aliases = {alias: slug for slug, club in clubs.items() for alias in club["aliases"]}
    if name not in aliases:
        raise ValueError(f"Unknown historical club: {name!r}")
    return aliases[name]


def normalize(matches: list[dict], clubs: dict) -> list[dict]:
    return [
        {**m, "home": resolve(m["home"], clubs), "away": resolve(m["away"], clubs)} for m in matches
    ]


def calculate_table(matches: list[dict], adjustments: dict | None = None) -> list[dict]:
    rows = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    for m in matches:
        for own, _other, gf, ga in (
            (m["home"], m["away"], m["home_goals"], m["away_goals"]),
            (m["away"], m["home"], m["away_goals"], m["home_goals"]),
        ):
            row = rows[own]
            row["played"] += 1
            row["goals_for"] += gf
            row["goals_against"] += ga
            row["wins" if gf > ga else "draws" if gf == ga else "losses"] += 1
    for slug, row in rows.items():
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
        row["point_adjustment"] = (adjustments or {}).get(slug, 0)
        row["points"] = 3 * row["wins"] + row["draws"] + row["point_adjustment"]
        row["club_slug"] = slug
    ordered = sorted(
        rows.values(),
        key=lambda r: (-r["points"], -r["goal_difference"], -r["goals_for"], r["club_slug"]),
    )
    for i, row in enumerate(ordered, 1):
        row["position"] = i
    return ordered


def load_fjelstul(path: Path, clubs: dict) -> dict:
    result = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            year = int(row["season"])
            if row["tier"] == "1" and 1992 <= year <= 2023:
                result[str(year)].append(
                    {
                        "club_slug": resolve(row["team_name"], clubs),
                        **{
                            field: int(row[field])
                            for field in (*FIELDS, "position", "point_adjustment")
                        },
                    }
                )
    return dict(result)


def verify_table(matches: list[dict], reference: list[dict]) -> None:
    actual = {
        r["club_slug"]: r
        for r in calculate_table(
            matches, {r["club_slug"]: r["point_adjustment"] for r in reference}
        )
    }
    if set(actual) != {r["club_slug"] for r in reference}:
        raise ValueError("Table club set differs from match data")
    for expected in reference:
        for field in FIELDS:
            if actual[expected["club_slug"]][field] != expected[field]:
                raise ValueError(
                    f"{matches[0]['season']} {expected['club_slug']} {field}: "
                    f"{actual[expected['club_slug']][field]} != {expected[field]}"
                )


CREDIT = (
    "Sources: match results from openfootball/england (CC0 1.0), "
    "https://github.com/openfootball/england; final tables through 2023/24 from "
    "the Fjelstul English Football Database, © 2024 Joshua C. Fjelstul, Ph.D., "
    "https://github.com/jfjelstul/englishfootball. Adapted: names normalized, "
    "tables converted to English summaries, team-season and head-to-head statistics computed. "
    "Historical documents are shared under CC-BY-SA 4.0: "
    "https://creativecommons.org/licenses/by-sa/4.0/legalcode."
)


def make_documents(seasons: dict, tables: dict, clubs: dict, source_urls: dict) -> list[dict]:
    documents, pairs = [], defaultdict(list)

    def doc(doc_id, title, text, topic, season, slugs, origin, url):
        return {
            "doc_id": doc_id,
            "title": title,
            "text": text + "\n## Sources and license\n" + CREDIT,
            "category": "historical",
            "origin": origin,
            "topic": topic,
            "season": season,
            "matchweek": None,
            "team_ids": sorted(
                {clubs[s]["team_id"] for s in slugs if clubs[s]["team_id"] is not None}
            ),
            "date": None,
            "fetched_at": None,
            "url": url,
        }

    def result(m):
        return (
            f"{m['date']} MW{m['matchweek']}: {clubs[m['home']]['name']} "
            f"{m['home_goals']}-{m['away_goals']} {clubs[m['away']]['name']}"
        )

    def stats(row):
        return (
            f"P{row['played']} W{row['wins']} D{row['draws']} L{row['losses']} "
            f"GF{row['goals_for']} GA{row['goals_against']} "
            f"GD{row['goal_difference']:+} Pts{row['points']}"
            + (f"; point adjustment {row['point_adjustment']}" if row["point_adjustment"] else "")
        )

    for season, matches in sorted(seasons.items()):
        rows = sorted(tables[season], key=lambda row: row["position"])
        title = f"Premier League {season}/{str(int(season) + 1)[2:]} final table"
        text = (
            f"Champions: {clubs[rows[0]['club_slug']]['name']}, {rows[0]['points']} points. "
            f"Runners-up: {clubs[rows[1]['club_slug']]['name']}, {rows[1]['points']} points.\n"
        )
        # 1994/95 relegated four clubs during the reduction from 22 to 20.
        relegated = rows[-(4 if season == "1994" else 3) :]
        text += "Relegated: " + ", ".join(clubs[r["club_slug"]]["name"] for r in relegated) + ".\n"
        for offset in range(0, len(rows), 5):
            text += f"## Table: positions {offset + 1}-{min(offset + 5, len(rows))}\n"
            text += (
                "\n".join(
                    f"{r['position']}. {clubs[r['club_slug']]['name']}: {stats(r)}"
                    for r in rows[offset : offset + 5]
                )
                + "\n"
            )
        biggest = max(matches, key=lambda m: abs(m["home_goals"] - m["away_goals"]))
        text += (
            f"## Season facts\nMatches: {len(matches)}. "
            f"Total goals: {sum(m['home_goals'] + m['away_goals'] for m in matches)}. "
            f"Biggest winning margin: {result(biggest)}."
        )
        documents.append(
            doc(
                f"hist-season-{season}",
                title,
                text,
                "season_table",
                season,
                [r["club_slug"] for r in rows],
                "fjelstul" if int(season) <= 2023 else "openfootball",
                "https://github.com/jfjelstul/englishfootball"
                if int(season) <= 2023
                else source_urls[season],
            )
        )
        for row in rows:
            slug = row["club_slug"]
            own = sorted(
                [m for m in matches if slug in (m["home"], m["away"])], key=lambda m: m["date"]
            )
            title = f"{clubs[slug]['name']} — Premier League {season}/{str(int(season) + 1)[2:]}"
            text = f"Final position: {row['position']}. {stats(row)}.\n## Home and away\n"
            for side in ("home", "away"):
                side_rows = calculate_table([m for m in own if m[side] == slug])
                side_row = next(r for r in side_rows if r["club_slug"] == slug)
                text += f"{side.title()}: {stats(side_row)}.\n"
            # Keep results sections short enough for retrieval's heading-based chunker.
            for offset in range(0, len(own), 5):
                text += f"## Results {offset + 1}-{min(offset + 5, len(own))}\n"
                text += "\n".join(result(m) for m in own[offset : offset + 5]) + "\n"
            documents.append(
                doc(
                    f"hist-team-{season}-{slug}",
                    title,
                    text,
                    "team_season",
                    season,
                    [slug],
                    "openfootball",
                    source_urls[season],
                )
            )
        for match in matches:
            pairs[tuple(sorted((match["home"], match["away"])))].append(match)
    for (a, b), matches in sorted(pairs.items()):
        names = {s: clubs[s]["name"] for s in (a, b)}

        def summary(items, a=a, b=b, names=names):
            wins = {a: 0, b: 0}
            draws = 0
            for m in items:
                if m["home_goals"] == m["away_goals"]:
                    draws += 1
                else:
                    wins[m["home"] if m["home_goals"] > m["away_goals"] else m["away"]] += 1
            return (
                f"{len(items)} meetings: {names[a]} won {wins[a]}, "
                f"draws {draws}, {names[b]} won {wins[b]}."
            )

        title = f"{names[a]} vs {names[b]} — Premier League head-to-head"
        text = "Coverage: 1992/93 to 2025/26. " + summary(matches) + "\n"
        text += "## Home and away\n" + "\n".join(
            f"At {names[s]} home: {summary([m for m in matches if m['home'] == s])}" for s in (a, b)
        )
        text += "\n## Recent meetings\n" + "\n".join(
            result(m) for m in sorted(matches, key=lambda m: m["date"], reverse=True)[:6]
        )
        text += "\n## Biggest wins\n" + "\n".join(
            result(
                max(
                    matches,
                    key=lambda m: (
                        (m["home_goals"] - m["away_goals"]) * (1 if m["home"] == s else -1)
                    ),
                )
            )
            for s in (a, b)
        )
        documents.append(
            doc(
                f"hist-h2h-{a}-{b}",
                title,
                text,
                "head_to_head",
                None,
                [a, b],
                "openfootball",
                "https://github.com/openfootball/england",
            )
        )
    return documents
