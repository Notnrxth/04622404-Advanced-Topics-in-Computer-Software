"""Local integration tests use fake upstream services and a real SQLite database."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import Match, WeeklyReport
from app.football import current_season, match_payload
from app.main import create_app
from app.service import ServiceError


def example_match(season: str) -> dict:
    return {
        "id": 12345,
        "season": {"startDate": f"{season}-08-01"},
        "matchday": 5,
        "utcDate": f"{season}-09-20T11:30:00Z",
        "status": "FINISHED",
        "homeTeam": {"id": 57, "name": "Arsenal FC"},
        "awayTeam": {"id": 61, "name": "Chelsea FC"},
        "score": {
            "fullTime": {"home": 2, "away": 1},
            "halfTime": {"home": 1, "away": 0},
        },
    }


def report_payload(season: str, matchweek: int) -> dict:
    return {
        "season": season,
        "matchweek": matchweek,
        "title": "สรุปฟุตบอล",
        "markdown": "อาร์เซนอลชนะเชลซี 2-1",
        "search_text_en": "Arsenal beat Chelsea 2-1 in Premier League matchweek 5.",
        "highlights": [],
        "status": "draft",
        "generated_at": "2026-09-21T09:00:00+07:00",
        "data_as_of": "2026-09-21T08:00:00+07:00",
        "edited_at": None,
        "edited_by": None,
        "published_at": None,
        "published_by": None,
    }


@pytest.mark.asyncio
async def test_ingest_replays_index_and_report_uses_completed_week(tmp_path):
    season = current_season()
    indexed = {}
    fail_once = {"value": True}

    async def upstream(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/teams"):
            return httpx.Response(
                200,
                json={
                    "teams": [
                        {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal"},
                        {"id": 61, "name": "Chelsea FC", "shortName": "Chelsea"},
                    ]
                },
            )
        if path.endswith("/matches"):
            return httpx.Response(200, json={"matches": [example_match(season)]})
        if path.endswith("/standings"):
            return httpx.Response(
                200,
                json={
                    "season": {"currentMatchday": 6},
                    "standings": [
                        {
                            "type": "TOTAL",
                            "table": [
                                {
                                    "position": position,
                                    "team": {"id": team_id, "name": name},
                                    "playedGames": 1,
                                    "won": int(position == 1),
                                    "draw": 0,
                                    "lost": int(position == 2),
                                    "goalsFor": goals_for,
                                    "goalsAgainst": goals_against,
                                    "goalDifference": goals_for - goals_against,
                                    "points": points,
                                }
                                for position, team_id, name, goals_for, goals_against, points in (
                                    (1, 57, "Arsenal FC", 2, 1, 3),
                                    (2, 61, "Chelsea FC", 1, 2, 0),
                                )
                            ],
                        }
                    ],
                },
            )
        if path.endswith("/scorers"):
            return httpx.Response(200, json={"scorers": []})
        if path == "/index/upsert":
            if fail_once["value"]:
                fail_once["value"] = False
                return httpx.Response(503)
            for document in json.loads(request.content)["documents"]:
                indexed[document["doc_id"]] = document
            return httpx.Response(200, json={"upserted": 1})
        if path == "/report/weekly":
            return httpx.Response(
                200,
                json={"title": "สรุปสัปดาห์ที่ 5", "markdown": "อาร์เซนอลชนะ 2-1", "highlights": []},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'football.db'}",
        football_data_api_key="test-key",
    )
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    app = create_app(settings, http=upstream_client)
    async with app.router.lifespan_context(app):
        service = app.state.service
        with pytest.raises(ServiceError) as ingest_error:
            await service._ingest_primary(str(uuid4()))
        assert ingest_error.value.code == "INDEX_UPDATE_FAILED"
        status = await service.status()
        assert status["index_sync"]["pending"] > 0
        assert (await service.standings(season))["matchweek"] == 6

        await service.reconcile_index()
        assert (await service.status())["index_sync"]["pending"] == 0
        assert f"standings-{season}-mw05" in indexed
        assert f"match-{season}-mw05-57-61" in indexed

        await service._create_report(season, 5, str(uuid4()))
        report = await service.report(season, 5, published=False)
        assert report["status"] == "draft"
        assert "Arsenal FC 2-1 Chelsea FC" in report["search_text_en"]
    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_publish_commit_failure_restores_index_and_can_retry(tmp_path, monkeypatch):
    indexed = {}

    async def retrieval(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index/upsert":
            for document in json.loads(request.content)["documents"]:
                indexed[document["doc_id"]] = document
            return httpx.Response(200, json={"upserted": 1})
        if request.url.path.startswith("/index/") and request.method == "DELETE":
            indexed.pop(request.url.path.removeprefix("/index/"), None)
            return httpx.Response(200, json={"deleted": True})
        raise AssertionError(f"unexpected request: {request.url}")

    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'football.db'}")
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(retrieval))
    app = create_app(settings, http=upstream_client)
    async with app.router.lifespan_context(app):
        service = app.state.service
        season = current_season()
        async with service.sessions() as db:
            db.add(
                WeeklyReport(
                    season=season, matchweek=5, status="draft", payload=report_payload(season, 5)
                )
            )
            await db.commit()

        original_commit = AsyncSession.commit
        commits = {"count": 0}

        async def commit_with_failure(self):
            commits["count"] += 1
            if commits["count"] == 2:
                raise RuntimeError("simulated database commit failure")
            return await original_commit(self)

        monkeypatch.setattr(AsyncSession, "commit", commit_with_failure)
        with pytest.raises(ServiceError) as error:
            await service.publish(season, 5, "beat", str(uuid4()))
        assert error.value.code == "INDEX_UPDATE_FAILED"
        assert indexed == {}
        assert (await service.report(season, 5, published=False))["status"] == "draft"
        assert (await service.status())["index_sync"]["pending"] == 0

        published = await service.publish(season, 5, "beat", str(uuid4()))
        assert published["status"] == "published"
        document = indexed[f"weekly-{season}-mw05"]
        assert "Arsenal beat Chelsea" in document["text"]
        assert "อาร์เซนอล" not in document["text"]

        commits["count"] = 0
        with pytest.raises(ServiceError) as error:
            await service.unpublish(season, 5, "beat", str(uuid4()))
        assert error.value.code == "INDEX_UPDATE_FAILED"
        assert (await service.report(season, 5, published=True))["status"] == "published"
        assert f"weekly-{season}-mw05" in indexed
        assert (await service.status())["index_sync"]["pending"] == 0

        unpublished = await service.unpublish(season, 5, "beat", str(uuid4()))
        assert unpublished["status"] == "unpublished"
        assert indexed == {}
    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_detail_ingest_maps_fixture_and_persists_quota(tmp_path):
    season = current_season()
    fixture = {
        "fixture": {"id": 999, "date": f"{season}-09-20T11:30:00+00:00"},
        "teams": {"home": {"id": 111, "name": "Arsenal"}, "away": {"id": 222, "name": "Chelsea"}},
        "goals": {"home": 2, "away": 1},
    }
    calls = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/fixtures":
            return httpx.Response(200, json={"response": [fixture]})
        if request.url.path == "/fixtures/events":
            return httpx.Response(
                200,
                json={
                    "response": [
                        {
                            "time": {"elapsed": 12},
                            "team": {"id": 111},
                            "type": "Goal",
                            "detail": "Normal Goal",
                            "player": {"name": "Example Player"},
                            "assist": {"name": "Example Assist"},
                        }
                    ]
                },
            )
        if request.url.path in ("/fixtures/lineups", "/fixtures/statistics"):
            return httpx.Response(200, json={"response": []})
        if request.url.path == "/index/upsert":
            assert json.loads(request.content)["documents"][0]["origin"] == "api-football"
            return httpx.Response(200, json={"upserted": 1})
        raise AssertionError(f"unexpected request: {request.url}")

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'football.db'}",
        api_football_key="test-key",
    )
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    app = create_app(settings, http=upstream_client)
    async with app.router.lifespan_context(app):
        service = app.state.service
        match = match_payload(example_match(season), f"{season}-09-21T09:00:00+07:00")
        async with service.sessions() as db:
            db.add(
                Match(
                    match_id=match["match_id"],
                    external_id=12345,
                    season=season,
                    matchweek=5,
                    home_team_id=57,
                    away_team_id=61,
                    status="FINISHED",
                    payload=match,
                )
            )
            await db.commit()
        await service._ingest_details(str(uuid4()))
        enriched = await service.match(match["match_id"])
        assert enriched["external_ids"]["api_football"] == 999
        assert enriched["events"][0]["team_id"] == 57
        assert enriched["detail_source"] == "api-football"
        assert (await service.status())["quota"]["api_football_used_today"] == 4
        count = len(calls)
        await service._ingest_details(str(uuid4()))
        assert len(calls) == count
    await upstream_client.aclose()
