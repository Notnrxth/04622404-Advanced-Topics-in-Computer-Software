"""football-data.org adapter and contract-shaped payloads."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings

BANGKOK = ZoneInfo("Asia/Bangkok")
BASE = "https://football-assistant.local/match/"
STATUS = {
    "TIMED": "SCHEDULED",
    "SCHEDULED": "SCHEDULED",
    "IN_PLAY": "LIVE",
    "PAUSED": "LIVE",
    "LIVE": "LIVE",
    "FINISHED": "FINISHED",
    "POSTPONED": "POSTPONED",
    "CANCELLED": "CANCELLED",
    "SUSPENDED": "POSTPONED",
}
ALIASES = json.loads((Path(__file__).parent / "team_aliases.json").read_text(encoding="utf-8"))


def normalize_team_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).casefold()
    name = re.sub(r"\b(fc|afc|football club)\b", "", name)
    return re.sub(r"[^a-z0-9]+", "", name)


NORMALIZED_ALIASES = {normalize_team_name(name): aliases for name, aliases in ALIASES.items()}


def now_iso() -> str:
    return datetime.now(BANGKOK).isoformat(timespec="seconds")


def bangkok_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(BANGKOK).isoformat(timespec="seconds")


def current_season() -> str:
    now = datetime.now(BANGKOK)
    return str(now.year if now.month >= 7 else now.year - 1)


def team_payload(raw: dict) -> dict:
    name = raw["name"]
    local_aliases = NORMALIZED_ALIASES.get(normalize_team_name(name), [])
    aliases = list(dict.fromkeys([raw.get("shortName") or name, name, *local_aliases]))
    return {
        "team_id": raw["id"],
        "name": name,
        "short_name": raw.get("shortName") or name,
        "tla": raw.get("tla") or "",
        "aliases": aliases,
        "crest_url": raw.get("crest"),
    }


def match_payload(raw: dict, fetched_at: str) -> dict:
    home, away = raw["homeTeam"], raw["awayTeam"]
    score = raw.get("score") or {}
    full = score.get("fullTime") or {}
    half = score.get("halfTime") or {}
    season = str(raw["season"]["startDate"][:4])
    external_id = raw["id"]
    return {
        "match_id": str(uuid5(NAMESPACE_URL, BASE + str(external_id))),
        "external_ids": {"football_data": external_id, "api_football": None},
        "season": season,
        "matchweek": raw.get("matchday"),
        "kickoff": bangkok_iso(raw["utcDate"]),
        "status": STATUS.get(raw["status"], "SCHEDULED"),
        "home": {"team_id": home["id"], "name": home["name"]},
        "away": {"team_id": away["id"], "name": away["name"]},
        "score": {
            "home": full.get("home"),
            "away": full.get("away"),
            "half_time": {"home": half.get("home"), "away": half.get("away")},
        },
        "events": [],
        "lineups": None,
        "statistics": None,
        "fetched_at": fetched_at,
        "detail_source": "none",
    }


def standing_payload(raw: dict, season: str, fetched_at: str) -> dict:
    standings = raw.get("standings") or []
    total = next((part for part in standings if part.get("type") == "TOTAL"), {})
    rows = [
        {
            "position": row["position"],
            "team_id": row["team"]["id"],
            "name": row["team"]["name"],
            "played": row["playedGames"],
            "won": row["won"],
            "draw": row["draw"],
            "lost": row["lost"],
            "goals_for": row["goalsFor"],
            "goals_against": row["goalsAgainst"],
            "goal_difference": row["goalDifference"],
            "points": row["points"],
            "form": row.get("form") or "",
        }
        for row in total.get("table", [])
    ]
    return {
        "season": season,
        "matchweek": raw.get("season", {}).get("currentMatchday"),
        "fetched_at": fetched_at,
        "rows": rows,
    }


def scorer_payload(raw: dict) -> list[dict]:
    return [
        {
            "player": row["player"]["name"],
            "team_id": row["team"]["id"],
            "goals": row.get("goals") or 0,
            "assists": row.get("assists") or 0,
        }
        for row in raw.get("scorers", [])
    ]


def completed_matchweeks(matches: list[dict]) -> list[int]:
    weeks = sorted({m["matchweek"] for m in matches if m["matchweek"] is not None})
    return [
        week
        for week in weeks
        if all(
            m["status"] in ("FINISHED", "POSTPONED", "CANCELLED")
            for m in matches
            if m["matchweek"] == week
        )
    ]


def derive_standings(
    matches: list[dict],
    teams: list[dict],
    season: str,
    matchweek: int,
    fetched_at: str,
    reference_rows: list[dict] | None = None,
) -> dict:
    """Build a provisional snapshot, retaining known official point adjustments."""
    adjustments = {
        row["team_id"]: row["points"] - 3 * row["won"] - row["draw"]
        for row in reference_rows or []
        if all(key in row for key in ("team_id", "points", "won", "draw"))
    }
    rank_hints = {
        row["team_id"]: row["position"]
        for row in reference_rows or []
        if "team_id" in row and "position" in row
    }
    rows = {
        team["team_id"]: {
            "position": 0,
            "team_id": team["team_id"],
            "name": team["name"],
            "played": 0,
            "won": 0,
            "draw": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
            "form": "",
        }
        for team in teams
    }
    ordered = sorted(
        (m for m in matches if m["matchweek"] is not None and m["matchweek"] <= matchweek),
        key=lambda m: m["kickoff"],
    )
    for match in ordered:
        if match["status"] != "FINISHED":
            continue
        home_id, away_id = match["home"]["team_id"], match["away"]["team_id"]
        home_score, away_score = match["score"]["home"], match["score"]["away"]
        if home_score is None or away_score is None:
            raise ValueError("finished match has no score")
        for team_id, goals_for, goals_against in (
            (home_id, home_score, away_score),
            (away_id, away_score, home_score),
        ):
            row = rows[team_id]
            row["played"] += 1
            row["goals_for"] += goals_for
            row["goals_against"] += goals_against
            row["goal_difference"] += goals_for - goals_against
            result = (
                "W" if goals_for > goals_against else "D" if goals_for == goals_against else "L"
            )
            row[{"W": "won", "D": "draw", "L": "lost"}[result]] += 1
            row["points"] += {"W": 3, "D": 1, "L": 0}[result]
            row["form"] = (row["form"] + result)[-5:]
    for team_id, row in rows.items():
        row["point_adjustment"] = adjustments.get(team_id, 0)
        row["points"] += row["point_adjustment"]
    ranked = sorted(
        rows.values(),
        key=lambda row: (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            rank_hints.get(row["team_id"], len(rows) + 1),
            row["name"],
        ),
    )
    for position, row in enumerate(ranked, start=1):
        row["position"] = position
    return {
        "season": season,
        "matchweek": matchweek,
        "fetched_at": fetched_at,
        "rows": ranked,
        "provisional": True,
    }


class UpstreamError(Exception):
    pass


class PrimaryThrottle:
    """Pause before the next call once football-data.org reports the minute quota spent."""

    WINDOW_SECONDS = 60

    def __init__(self, sleep=asyncio.sleep):
        self._sleep = sleep
        self._remaining: int | None = None
        self._reset = self.WINDOW_SECONDS

    @staticmethod
    def _header_int(headers: httpx.Headers, name: str) -> int | None:
        try:
            value = int(headers.get(name, ""))
        except ValueError:
            return None
        return value if value >= 0 else None

    def observe(self, headers: httpx.Headers) -> None:
        remaining = self._header_int(headers, "x-requests-available-minute")
        if remaining is None:
            return
        self._remaining = remaining
        reset = self._header_int(headers, "X-RequestCounter-Reset")
        self._reset = reset if reset is not None else self.WINDOW_SECONDS

    def block(self, headers: httpx.Headers) -> None:
        """Treat a 429 as an exhausted minute even when it carries no counters."""
        self.observe(headers)
        self._remaining = 0

    async def wait(self) -> None:
        if self._remaining == 0:
            self._remaining = None
            await self._sleep(self._reset)


async def fetch_primary(
    http: httpx.AsyncClient,
    settings: Settings,
    path: str,
    season: str,
    request_id: str,
    throttle: PrimaryThrottle | None = None,
) -> dict:
    if not settings.football_data_api_key:
        raise UpstreamError("FOOTBALL_DATA_API_KEY is not configured")
    url = f"{settings.football_data_base_url.rstrip('/')}/{path.lstrip('/')}"
    for attempt in range(3):
        if throttle:
            await throttle.wait()
        try:
            response = await http.get(
                url,
                params={"season": season},
                headers={
                    "X-Auth-Token": settings.football_data_api_key,
                    "X-Request-ID": request_id,
                },
                timeout=10,
            )
            if throttle:
                throttle.observe(response.headers)
            if response.status_code == 429 and throttle and attempt < 2:
                throttle.block(response.headers)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep((1, 3)[attempt])
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 2:
                raise UpstreamError(str(exc)) from exc
            await asyncio.sleep((1, 3)[attempt])
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise UpstreamError(str(exc)) from exc
    raise UpstreamError("football-data.org unavailable")
