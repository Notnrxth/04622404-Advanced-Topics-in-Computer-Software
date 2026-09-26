# Historical data and provider verification — module 07

## Local result (2026-09-27)

Prepared 34 completed seasons (1992/93–2025/26), 13,166 matches, 51 clubs and 686 team-season tables. All 95 openfootball name variants resolve explicitly. Unknown names fail instead of being skipped.

The English document bundle contains 1,661 stable IDs: 34 season tables, 686 team-season summaries and 941 head-to-head summaries. Full results stay in football.historical_matches; tables in football.historical_standings. SQLite history_local.db is used locally and remains separate from current-season DB/index.

Mapping football-data.org team IDs is conservative: 20 identities verified against the current provider response; other clubs have null until verified. Fjelstul identities are resolved through its teams.csv and included in the generated clubs.json. Slugs do not depend on provider IDs.

## Reproduce (from services/07_football_data)

```powershell
.venv/Scripts/python scripts/ingest_history.py
# Cached input files are reused only if their pinned SHA-256 checksums match.
.venv/Scripts/python scripts/ingest_history.py --offline
.venv/Scripts/python scripts/verify_official_tables.py
.venv/Scripts/python -m pytest -q
```

The first command downloads public pinned files, checks them, builds documents and upserts the dedicated local database in one run. Generated documents, source inputs, cached provider responses and local databases are ignored by Git. No football-data.co.uk files are loaded.

To target an existing PostgreSQL football schema, explicitly supply --database-url; PostgreSQL runtime and migration are not yet tested. Nothing runs in beat automatically.

Sources are pinned to:

- openfootball/england: b17e8f01707d83d2ce1790c14d4a5eeb35987825
- jfjelstul/englishfootball: ff3c37698065476e1852243685da6b756a580b9f

32 overlapping seasons match the Fjelstul reference in P/W/D/L, GF/GA/GD and adjusted points. Deductions are retained, including Middlesbrough −3 (1996), Portsmouth −9 (2009), Everton −8 and Nottingham Forest −4 (2023). Reference positions are preserved, not replaced by a computed alphabetical tie-break.

For 2024 and 2025, all 20 positions, P/W/D/L, GF/GA and points were compared with the public final-MW38 standings endpoint used by the [official PL tables page](https://www.premierleague.com/en/tables/premier-league). Both require no deductions. Evidence URLs and review status are in data/point_deductions.json. The saved official response SHA-256 values are:

- 2024: 8f369b9620f889dd1039c380b43c98f9b9044cbd8ef7692015ff40fb296d08a2
- 2025: f1ae6987280eccd02dab014a6b52cbcd6e75897e0c7344eef205ed303cf4f33e

## Index integration remains gated

docs/05_RETRIEVAL_DESIGN.md §10 in develop is a proposal requiring a CONTRACT agreement. This branch does not modify peers' 05, 03 or web modules.

Historical metadata uses category=historical, origin=openfootball|fjelstul, topic=season_table|team_season|head_to_head. Historical fetched_at/date/matchweek are null; h2h season is null. The existing 05 currently rejects the new category/origin/IDs.

Therefore --index is disabled unless HISTORICAL_INDEX_ENABLED=true is explicitly configured **after** agreement and 05 support. Worker also refuses historical writes while disabled. Once supported, --index queues durable outbox tasks in the selected DB and reconciles in batches of at most 50 documents, each bounded by UTF-8 body size.

Do not enable on the current 05 yet. 03 must support historical filters, and web must display source attribution. Current history documents produce approximately 12,558 heading-based chunks (more than the early estimate because results sections are shorter); real-model embedding time, retrieval latency and trivia/history eval must be measured before launch. No performance claim is made here.

## Real API findings and fallback

Credentials are stored only in ignored repository-root .env. Do not copy them to source, screenshots, logs or commits. When running locally:

```powershell
.venv/Scripts/python scripts/check_providers.py
.venv/Scripts/python scripts/demo_details.py
.venv/Scripts/python scripts/demo_details.py --offline
.venv/Scripts/uvicorn app.main:app --env-file ../../.env --port 8007
```

check_providers consumes up to seven API-Football requests on the verified Free plan; demo_details consumes one additional fixture request, or none with --offline. These diagnostic requests are not in the service's DB quota counter; account quota in the provider dashboard remains authoritative.

Observed:
- football-data.org: teams (20), matches (380), standings and scorers (10) all HTTP 200.
- API-Football: Free subscription active, limit 100/day. Seasons 2026 and 2025 respond HTTP 200 **with a plan error**, not valid empty results. Allowed range stated by provider: 2022–2024.
- Season 2024 returns 380 finished matches; fixture 1208399 (Nottingham Forest 0–1 Chelsea) returns 11 events, two lineups and two team-statistic entries.
- Local normalization preserves this as a **demo-only 2024/25** artifact, with correct team identities. It is never written into current-season DB/index.

Use scope=fixtures for current-season ingest on this Free plan (football-data.org only). Do not use scope=all/details until the plan actually supports the current season; the service rejects provider plan errors rather than inventing details. Historical data sources do not contain comprehensive shot/corner/card/referee statistics. Older API data is a limited demo, not a replacement for 34 seasons of those statistics.

## Credits and license

Match data: [openfootball/england](https://github.com/openfootball/england), [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

Final-table reference: **The Fjelstul English Football Database**, © 2024 **Joshua C. Fjelstul, Ph.D.**, [source repository](https://github.com/jfjelstul/englishfootball), [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/legalcode).

Adapted: names normalized; tables converted to English text summaries; team-season and head-to-head statistics computed. Generated historical data/documents are distributed under CC-BY-SA 4.0. This declaration covers the historical data/documents, not an automatic relicensing of the service code. Each generated document includes full source/license attribution.

Fjelstul is a compiled reference database whose author describes Wikipedia and cross-validation as its sources, not a PL-owned API. Recent tables are separately checked against PL.

Keep the required data-source credit in README and presentation materials, and source links in answers.

## Validation status

Final local run: **29 passed** (14.90 seconds), including optional localhost 05 HTTP integration; ruff check and format check passed (23 Python files), git diff --check passed apart from LF/CRLF notices. Credential scan found zero key matches in tracked/unignored files. Root .env, raw inputs/generated bundles and local DB are ignored.

Regression coverage includes July 2020 dates in the COVID-delayed 2019/20 season. After regeneration, the final date is 2020-07-26; no July matches are incorrectly assigned to 2019.

Unit/parser tests require no network/key. Full pinned-data tests and cached-real-provider tests skip when local inputs are absent. The optional actual-05 HTTP test remains FakeEmbedder-based, with mocked Generation; historical indexing is not claimed as end-to-end validated.
