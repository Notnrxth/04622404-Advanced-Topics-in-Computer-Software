"""Premier League club records and league-wide honours, computed from the final tables."""

from collections import Counter, defaultdict

from app.history import FIELDS, historical_document, relegated, season_label, table_stats

FJELSTUL_URL = "https://github.com/jfjelstul/englishfootball"
GROUP = 10  # rows per heading, sized for retrieval's heading-based chunker


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _labels(seasons: list[str]) -> str:
    return ", ".join(season_label(s) for s in seasons)


def _counted(label: str, seasons: list[str]) -> str:
    return f"{label}: {len(seasons)}" + (f" ({_labels(seasons)})" if seasons else "") + "."


def _subject(n: int, noun: str) -> str:
    return f"{n} {noun}s have" if n != 1 else f"{n} {noun} has"


def _totals(rows: list[dict]) -> dict:
    return {field: sum(row[field] for row in rows) for field in FIELDS}


def _groups(items: list) -> list[list]:
    return [items[offset : offset + GROUP] for offset in range(0, len(items), GROUP)]


def make_record_documents(tables: dict, clubs: dict) -> list[dict]:
    seasons = sorted(tables)
    first, last = season_label(seasons[0]), season_label(seasons[-1])
    span = f"{first}–{last}"
    coverage = (
        f"Coverage: Premier League seasons {first} to {last} only. Top-flight league titles "
        "won before the Premier League began in 1992 (First Division) are not included.\n"
    )
    history = defaultdict(list)  # slug -> [(season, row, relegated?)] in season order
    for season in seasons:
        down = {row["club_slug"] for row in relegated(season, tables[season])}
        for row in sorted(tables[season], key=lambda r: r["position"]):
            history[row["club_slug"]].append((season, row, row["club_slug"] in down))
    documents = [
        _club_document(slug, history[slug], clubs, coverage, span, len(seasons))
        for slug in sorted(history)
    ]
    documents.append(_records_document(seasons, tables, history, clubs, coverage, span))
    return documents


def _club_document(slug, entries, clubs, coverage, span, total) -> dict:
    name = clubs[slug]["name"]
    titles = [s for s, row, _ in entries if row["position"] == 1]
    runners_up = [s for s, row, _ in entries if row["position"] == 2]
    relegations = [s for s, _, down in entries if down]
    positions = [row["position"] for _, row, _ in entries]
    best, worst = min(positions), max(positions)
    best_count = positions.count(best)
    # Plain sentences (English and Thai) so keyword search matches how fans ask.
    times = {0: None, 1: "once"}.get(len(titles), f"{len(titles)} times")
    text = coverage + (
        f"{name} have won the Premier League title {times}.\n"
        if times
        else f"{name} have never won the Premier League title.\n"
    )
    text += (
        f"สรุปสถิติพรีเมียร์ลีกของ {name}: "
        + (f"ได้แชมป์พรีเมียร์ลีก {len(titles)} สมัย" if titles else "ไม่เคยได้แชมป์พรีเมียร์ลีก")
        + f" รองแชมป์ {len(runners_up)} ครั้ง อยู่พรีเมียร์ลีก {len(entries)} จาก {total} ฤดูกาล"
        + f" ตกชั้น {len(relegations)} ครั้ง อันดับดีที่สุดอันดับ {best}"
        + f" อันดับแย่ที่สุดอันดับ {worst}\n"
    )
    text += (
        _counted("Premier League titles", titles)
        if titles
        else "Premier League titles: 0 (never won the Premier League)."
    )
    text += "\n" + _counted("Runners-up", runners_up)
    text += f"\nSeasons in the Premier League: {len(entries)} of {total}. "
    text += _counted("Relegations", relegations)
    text += (
        f"\nBest finish: {ordinal(best)} ({best_count} time{'s' if best_count != 1 else ''}). "
        f"Worst finish: {ordinal(worst)} "
        f"({_labels([s for s, row, _ in entries if row['position'] == worst])}).\n"
    )
    text += (
        f"All-time Premier League record: {table_stats(_totals([row for _, row, _ in entries]))}.\n"
    )
    for group in _groups(entries):
        text += f"## Finishes by season {season_label(group[0][0])}–{season_label(group[-1][0])}\n"
        text += "".join(
            f"{season_label(s)}: {ordinal(row['position'])}, {row['points']} pts"
            + (
                f" (point adjustment {row['point_adjustment']})"
                if row.get("point_adjustment")
                else ""
            )
            + "\n"
            for s, row, _ in group
        )
    return historical_document(
        clubs,
        f"hist-club-{slug}",
        f"{name} — Premier League record {span}",
        text,
        "club_record",
        None,
        [slug],
        "fjelstul",
        FJELSTUL_URL,
    )


def _records_document(seasons, tables, history, clubs, coverage, span) -> dict:
    def name(slug):
        return clubs[slug]["name"]

    def at(season, position):
        return next(r["club_slug"] for r in tables[season] if r["position"] == position)

    champions = Counter(at(s, 1) for s in seasons)
    ranked = sorted(champions.items(), key=lambda item: (-item[1], name(item[0])))
    most = ranked[0][1]
    leaders = ", ".join(name(slug) for slug, count in ranked if count == most)
    text = coverage + "## Titles by club\n"
    text += f"Most Premier League titles: {leaders} ({most}).\n"
    text += (
        f"ทีมที่ได้แชมป์พรีเมียร์ลีกมากที่สุดคือ {leaders} ({most} สมัย) "
        f"มีทั้งหมด {len(champions)} ทีมที่เคยได้แชมป์พรีเมียร์ลีก\n"
    )
    text += " · ".join(f"{name(slug)} {count}" for slug, count in ranked) + ".\n"
    text += f"{_subject(len(champions), 'different club')} won the Premier League.\n"
    for group in _groups(seasons):
        text += f"## Champions and runners-up {season_label(group[0])}–{season_label(group[-1])}\n"
        text += "".join(
            f"{season_label(s)}: {name(at(s, 1))} (runners-up {name(at(s, 2))})\n" for s in group
        )
    ever = sorted((s for s, e in history.items() if len(e) == len(seasons)), key=name)
    text += "## Ever-present clubs\n" + (
        f"มี {len(ever)} ทีมที่อยู่พรีเมียร์ลีกครบทุกฤดูกาล ({len(seasons)} ฤดูกาล) และไม่เคยตกชั้น\n"
        f"{_subject(len(ever), 'club')} played in all {len(seasons)} Premier League seasons: "
        + ", ".join(name(s) for s in ever)
        + ".\n"
        if ever
        else "ไม่มีทีมใดอยู่พรีเมียร์ลีกครบทุกฤดูกาล\n"
        f"No club has played in all {len(seasons)} Premier League seasons.\n"
    )
    totals = {slug: _totals([row for _, row, _ in e]) for slug, e in history.items()}
    order = sorted(
        totals,
        key=lambda s: (
            -totals[s]["points"],
            -totals[s]["goal_difference"],
            -totals[s]["goals_for"],
            name(s),
        ),
    )
    for index, group in enumerate(_groups(order)):
        start = index * GROUP + 1
        text += f"## All-time table: positions {start}-{start + len(group) - 1}\n"
        if index == 0:
            text += (
                "ตารางคะแนนรวมตลอดกาลของพรีเมียร์ลีก ทีมที่เก็บแต้มรวมมากที่สุดคือ "
                f"{name(order[0])} ({totals[order[0]]['points']} แต้ม)\n"
            )
        text += "".join(
            f"{start + i}. {name(s)}: {table_stats(totals[s])}\n" for i, s in enumerate(group)
        )
    return historical_document(
        clubs,
        "hist-records",
        f"Premier League honours and all-time records {span}",
        text,
        "league_records",
        None,
        sorted(history),
        "fjelstul",
        FJELSTUL_URL,
    )
