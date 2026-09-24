"""football-data.org adapter and contract-shaped payloads."""

from __future__ import annotations

import json
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
    aliases = list(dict.fromkeys([raw.get("shortName") or name, name, *ALIASES.get(name, [])]))
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


class UpstreamError(Exception):
    pass


async def fetch_primary(
    http: httpx.AsyncClient, settings: Settings, path: str, season: str, request_id: str
) -> dict:
    if not settings.football_data_api_key:
        raise UpstreamError("FOOTBALL_DATA_API_KEY is not configured")
    url = f"{settings.football_data_base_url.rstrip('/')}/{path.lstrip('/')}"
    for attempt in range(3):
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
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                import asyncio

                await asyncio.sleep((1, 3)[attempt])
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 2:
                raise UpstreamError(str(exc)) from exc
            import asyncio

            await asyncio.sleep((1, 3)[attempt])
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise UpstreamError(str(exc)) from exc
    raise UpstreamError("football-data.org unavailable")
