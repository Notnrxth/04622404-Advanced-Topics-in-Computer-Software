"""Database operations and scheduled ingestion/report jobs."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db import Job, Match, Scorers, ServiceState, Standing, Team, WeeklyReport
from app.football import (
    current_season,
    fetch_primary,
    match_payload,
    now_iso,
    scorer_payload,
    standing_payload,
    team_payload,
)

BANGKOK = ZoneInfo("Asia/Bangkok")


class ServiceError(Exception):
    def __init__(self, code: str, status: int, detail: str):
        self.code, self.status, self.detail = code, status, detail
        super().__init__(detail)


def job_dict(row: Job) -> dict:
    return {
        "job_id": row.job_id,
        "kind": row.kind,
        "scope": row.scope,
        "status": row.status,
        "triggered_by": row.triggered_by,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "detail": row.detail,
    }


def report_doc(report: dict) -> dict:
    season, week = report["season"], report["matchweek"]
    return {
        "doc_id": f"weekly-{season}-mw{week:02d}",
        "title": report["title"],
        "text": report["markdown"],
        "category": "weekly_report",
        "origin": "generated",
        "season": season,
        "matchweek": week,
        "team_ids": [],
        "date": report["data_as_of"][:10],
        "fetched_at": report["data_as_of"],
        "url": None,
    }


class FootballService:
    def __init__(self, settings: Settings, sessions: async_sessionmaker, http: httpx.AsyncClient):
        self.settings, self.sessions, self.http = settings, sessions, http
        self._job_lock = asyncio.Lock()

    async def status(self) -> dict:
        season = current_season()
        async with self.sessions() as db:
            state = await db.get(ServiceState, "last_ingest_at")
            standing = await db.scalar(
                select(Standing)
                .where(Standing.season == season)
                .order_by(Standing.matchweek.desc())
                .limit(1)
            )
            reports = await db.scalars(
                select(WeeklyReport).where(
                    WeeklyReport.season == season, WeeklyReport.status == "published"
                )
            )
            weeks = [r.matchweek for r in reports]
        now = datetime.now(BANGKOK)
        reset = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if reset <= now:
            from datetime import timedelta

            reset += timedelta(days=1)
        return {
            "current_season": season,
            "current_matchweek": standing.payload.get("matchweek") if standing else None,
            "last_ingest_at": state.value if state else None,
            "last_report_matchweek": max(weeks) if weeks else None,
            "quota": {
                "api_football_used_today": 0,
                "api_football_limit": self.settings.api_football_daily_limit,
                "reset_at": reset.isoformat(timespec="seconds"),
            },
        }

    async def teams(self) -> dict:
        async with self.sessions() as db:
            rows = (await db.scalars(select(Team).order_by(Team.team_id))).all()
            return {"teams": [row.payload for row in rows]}

    async def standings(self, season: str | None) -> dict:
        async with self.sessions() as db:
            row = await db.scalar(
                select(Standing)
                .where(Standing.season == (season or current_season()))
                .order_by(Standing.matchweek.desc())
                .limit(1)
            )
            if row is None:
                raise ServiceError("NOT_FOUND", 404, "ยังไม่มีตารางคะแนนของฤดูกาลนี้")
            return row.payload

    async def fixtures(
        self, season: str | None, matchweek: int | None, team_id: int | None, status: str | None
    ) -> dict:
        selected = season or current_season()
        query = select(Match).where(Match.season == selected)
        if matchweek is not None:
            query = query.where(Match.matchweek == matchweek)
        if status:
            query = query.where(Match.status == status)
        if team_id is not None:
            query = query.where((Match.home_team_id == team_id) | (Match.away_team_id == team_id))
        async with self.sessions() as db:
            matches = (await db.scalars(query)).all()
            state = await db.get(ServiceState, "last_ingest_at")
        matches.sort(key=lambda row: row.payload["kickoff"])
        return {
            "season": selected,
            "fetched_at": state.value if state else None,
            "matches": [row.payload for row in matches],
        }

    async def match(self, match_id: str) -> dict:
        async with self.sessions() as db:
            row = await db.get(Match, match_id)
            if row is None:
                raise ServiceError("NOT_FOUND", 404, "ไม่พบนัดการแข่งขัน")
            return row.payload

    async def list_jobs(self, kind: str | None, status: str | None, limit: int) -> dict:
        query = select(Job)
        if kind:
            query = query.where(Job.kind == kind)
        if status:
            query = query.where(Job.status == status)
        query = query.order_by(Job.started_at.desc()).limit(limit)
        async with self.sessions() as db:
            rows = (await db.scalars(query)).all()
        return {"jobs": [job_dict(row) for row in rows]}

    async def get_job(self, job_id: str) -> dict:
        async with self.sessions() as db:
            row = await db.get(Job, job_id)
            if row is None:
                raise ServiceError("NOT_FOUND", 404, "ไม่พบงาน")
            return job_dict(row)

    async def start_job(
        self, kind: str, scope: str | None, triggered_by: str, request_id: str
    ) -> str:
        async with self._job_lock:
            async with self.sessions() as db:
                active = await db.scalar(
                    select(Job.job_id).where(
                        Job.kind == kind, Job.status.in_(["queued", "running"])
                    )
                )
                if active:
                    raise ServiceError("JOB_ALREADY_RUNNING", 409, "มีงานชนิดเดียวกันกำลังทำงาน")
                job_id = str(uuid4())
                db.add(
                    Job(
                        job_id=job_id,
                        request_id=request_id,
                        kind=kind,
                        scope=scope,
                        status="queued",
                        triggered_by=triggered_by,
                        started_at=datetime.now(BANGKOK),
                    )
                )
                await db.commit()
                return job_id

    async def _finish_job(self, job_id: str, detail: str | None) -> None:
        async with self.sessions() as db:
            job = await db.get(Job, job_id)
            job.status = "failed" if detail else "done"
            job.detail = detail
            job.finished_at = datetime.now(BANGKOK)
            await db.commit()

    async def run_ingest(self, job_id: str, scope: str, request_id: str) -> None:
        async with self.sessions() as db:
            job = await db.get(Job, job_id)
            job.status = "running"
            await db.commit()
        try:
            if scope in ("fixtures", "all"):
                await self._ingest_primary(request_id)
            if scope in ("details", "all"):
                # Detailed event ingestion needs API-Football ID mapping and quota persistence.
                raise ServiceError("NOT_IMPLEMENTED", 501, "ยังไม่รองรับการดึงรายละเอียดนัด")
            await self._finish_job(job_id, None)
        except Exception as exc:
            await self._finish_job(job_id, f"{type(exc).__name__}: {exc}")

    async def _ingest_primary(self, request_id: str) -> None:
        season = current_season()
        # Fetch all responses before changing any database rows.
        teams_raw = await fetch_primary(
            self.http, self.settings, "competitions/PL/teams", season, request_id
        )
        matches_raw = await fetch_primary(
            self.http, self.settings, "competitions/PL/matches", season, request_id
        )
        standings_raw = await fetch_primary(
            self.http, self.settings, "competitions/PL/standings", season, request_id
        )
        scorers_raw = await fetch_primary(
            self.http, self.settings, "competitions/PL/scorers", season, request_id
        )
        fetched_at = now_iso()
        teams = [team_payload(item) for item in teams_raw.get("teams", [])]
        matches = [match_payload(item, fetched_at) for item in matches_raw.get("matches", [])]
        standing = standing_payload(standings_raw, season, fetched_at)
        scorers = scorer_payload(scorers_raw)
        async with self.sessions() as db:
            for item in teams:
                await db.merge(Team(team_id=item["team_id"], payload=item))
            for item in matches:
                await db.merge(
                    Match(
                        match_id=item["match_id"],
                        external_id=item["external_ids"]["football_data"],
                        season=season,
                        matchweek=item["matchweek"],
                        home_team_id=item["home"]["team_id"],
                        away_team_id=item["away"]["team_id"],
                        status=item["status"],
                        payload=item,
                    )
                )
            await db.merge(
                Standing(season=season, matchweek=standing["matchweek"] or 0, payload=standing)
            )
            await db.merge(
                Scorers(season=season, payload={"items": scorers, "fetched_at": fetched_at})
            )
            await db.merge(ServiceState(key="last_ingest_at", value=fetched_at))
            await db.commit()
        # A failed index write leaves the job failed so a retry can repair the index.
        documents = self._documents(matches, standing, season, fetched_at)
        for start in range(0, len(documents), 50):
            response = await self.http.post(
                f"{self.settings.retrieval_url.rstrip('/')}/index/upsert",
                json={"request_id": request_id, "documents": documents[start : start + 50]},
                headers={"X-Request-ID": request_id},
                timeout=30,
            )
            response.raise_for_status()

    @staticmethod
    def _documents(matches: list[dict], standing: dict, season: str, fetched_at: str) -> list[dict]:
        documents = []
        for match in matches:
            if match["status"] != "FINISHED" or match["matchweek"] is None:
                continue
            home, away = match["home"], match["away"]
            week = match["matchweek"]
            title = (
                f"{home['name']} {match['score']['home']}-{match['score']['away']} {away['name']}"
            )
            documents.append(
                {
                    "doc_id": f"match-{season}-mw{week:02d}-{home['team_id']}-{away['team_id']}",
                    "title": title,
                    "text": (
                        f"Premier League {season}, matchweek {week}. {title}. "
                        f"Kickoff: {match['kickoff']}."
                    ),
                    "category": "match_report",
                    "origin": "football-data.org",
                    "season": season,
                    "matchweek": week,
                    "team_ids": [home["team_id"], away["team_id"]],
                    "date": match["kickoff"][:10],
                    "fetched_at": fetched_at,
                    "url": None,
                }
            )
        week = standing.get("matchweek")
        if week is not None:
            rows = standing["rows"]
            documents.append(
                {
                    "doc_id": f"standings-{season}-mw{week:02d}",
                    "title": f"Premier League {season} standings after matchweek {week}",
                    "text": "## Standings\n"
                    + "\n".join(
                        f"{r['position']}. {r['name']}: {r['points']} points, "
                        f"played {r['played']}, "
                        f"goal difference {r['goal_difference']}"
                        for r in rows
                    ),
                    "category": "standings",
                    "origin": "football-data.org",
                    "season": season,
                    "matchweek": week,
                    "team_ids": [r["team_id"] for r in rows],
                    "date": fetched_at[:10],
                    "fetched_at": fetched_at,
                    "url": None,
                }
            )
        for team_id in {m["home"]["team_id"] for m in matches} | {
            m["away"]["team_id"] for m in matches
        }:
            upcoming = [
                m
                for m in matches
                if m["status"] == "SCHEDULED"
                and team_id in (m["home"]["team_id"], m["away"]["team_id"])
            ]
            documents.append(
                {
                    "doc_id": f"fixtures-{season}-team-{team_id}",
                    "title": f"Premier League {season} fixtures for team {team_id}",
                    "text": "## Upcoming fixtures\n"
                    + "\n".join(
                        f"{m['kickoff']}: {m['home']['name']} vs {m['away']['name']}"
                        for m in upcoming
                    ),
                    "category": "fixtures",
                    "origin": "football-data.org",
                    "season": season,
                    "matchweek": None,
                    "team_ids": [team_id],
                    "date": fetched_at[:10],
                    "fetched_at": fetched_at,
                    "url": None,
                }
            )
        return documents

    async def list_reports(self, status: str | None, season: str | None) -> dict:
        query = select(WeeklyReport)
        if status:
            query = query.where(WeeklyReport.status == status)
        if season:
            query = query.where(WeeklyReport.season == season)
        query = query.order_by(WeeklyReport.season.desc(), WeeklyReport.matchweek.desc())
        async with self.sessions() as db:
            rows = (await db.scalars(query)).all()
        return {"items": [row.payload for row in rows]}

    async def report(self, season: str | None, matchweek: int | None, *, published: bool) -> dict:
        async with self.sessions() as db:
            if season is not None and matchweek is not None:
                row = await db.get(WeeklyReport, (season, matchweek))
            else:
                query = select(WeeklyReport)
                if season:
                    query = query.where(WeeklyReport.season == season)
                if matchweek is not None:
                    query = query.where(WeeklyReport.matchweek == matchweek)
                if published:
                    query = query.where(WeeklyReport.status == "published")
                row = await db.scalar(
                    query.order_by(WeeklyReport.season.desc(), WeeklyReport.matchweek.desc()).limit(
                        1
                    )
                )
            if row is None or (published and row.status != "published"):
                raise ServiceError("NOT_FOUND", 404, "ไม่พบรายงานที่เผยแพร่แล้ว")
            return row.payload

    async def edit_report(
        self, season: str, matchweek: int, title: str | None, markdown: str | None, actor: str
    ) -> dict:
        async with self.sessions() as db:
            row = await db.get(WeeklyReport, (season, matchweek))
            if row is None:
                raise ServiceError("NOT_FOUND", 404, "ไม่พบรายงาน")
            if row.status == "published":
                raise ServiceError("REPORT_NOT_EDITABLE", 409, "ต้องยกเลิกเผยแพร่ก่อนแก้ไข")
            payload = dict(row.payload)
            if title is not None:
                payload["title"] = title
            if markdown is not None:
                payload["markdown"] = markdown
            payload["edited_at"] = now_iso()
            payload["edited_by"] = actor
            row.payload = payload
            await db.commit()
            return payload

    async def publish(self, season: str, matchweek: int, actor: str, request_id: str) -> dict:
        async with self.sessions() as db:
            row = await db.get(WeeklyReport, (season, matchweek))
            if row is None:
                raise ServiceError("NOT_FOUND", 404, "ไม่พบรายงาน")
            if row.status == "published":
                return row.payload
            payload = dict(row.payload)
            doc = report_doc(payload)
            try:
                response = await self.http.post(
                    f"{self.settings.retrieval_url.rstrip('/')}/index/upsert",
                    json={"request_id": request_id, "documents": [doc]},
                    headers={"X-Request-ID": request_id},
                    timeout=30,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ServiceError("INDEX_UPDATE_FAILED", 502, str(exc)) from exc
            payload.update(status="published", published_at=now_iso(), published_by=actor)
            row.status, row.payload = "published", payload
            await db.commit()
            return payload

    async def unpublish(self, season: str, matchweek: int, actor: str, request_id: str) -> dict:
        async with self.sessions() as db:
            row = await db.get(WeeklyReport, (season, matchweek))
            if row is None:
                raise ServiceError("NOT_FOUND", 404, "ไม่พบรายงาน")
            if row.status != "published":
                return row.payload
            try:
                response = await self.http.delete(
                    (
                        f"{self.settings.retrieval_url.rstrip('/')}/index/"
                        f"weekly-{season}-mw{matchweek:02d}"
                    ),
                    headers={"X-Request-ID": request_id},
                    timeout=30,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ServiceError("INDEX_UPDATE_FAILED", 502, str(exc)) from exc
            payload = dict(row.payload)
            payload.update(status="unpublished", published_at=None, published_by=None)
            row.status, row.payload = "unpublished", payload
            await db.commit()
            return payload

    async def run_report(
        self, job_id: str, season: str | None, matchweek: int | None, request_id: str
    ) -> None:
        async with self.sessions() as db:
            job = await db.get(Job, job_id)
            job.status = "running"
            await db.commit()
        try:
            await self._create_report(season, matchweek, request_id)
            await self._finish_job(job_id, None)
        except Exception as exc:
            await self._finish_job(job_id, f"{type(exc).__name__}: {exc}")

    async def _create_report(
        self, season: str | None, matchweek: int | None, request_id: str
    ) -> None:
        season = season or current_season()
        async with self.sessions() as db:
            if matchweek is None:
                weeks = (
                    await db.scalars(
                        select(Match.matchweek)
                        .where(Match.season == season, Match.matchweek.is_not(None))
                        .distinct()
                    )
                ).all()
                for week in sorted(weeks, reverse=True):
                    candidates = (
                        await db.scalars(
                            select(Match).where(Match.season == season, Match.matchweek == week)
                        )
                    ).all()
                    if candidates and all(
                        row.status in ("FINISHED", "POSTPONED", "CANCELLED") for row in candidates
                    ):
                        matchweek = week
                        break
            if matchweek is None:
                raise ServiceError("MATCHWEEK_NOT_COMPLETE", 409, "ยังไม่มีแมตช์วีคที่แข่งครบ")
            standings = await db.get(Standing, (season, matchweek))
            if standings is None:
                raise ServiceError("NOT_FOUND", 404, "ยังไม่มีตารางคะแนนหลังแมตช์วีคนี้")
            matches = (
                await db.scalars(
                    select(Match).where(Match.season == season, Match.matchweek == matchweek)
                )
            ).all()
            if not matches or any(
                row.status not in ("FINISHED", "POSTPONED", "CANCELLED") for row in matches
            ):
                raise ServiceError("MATCHWEEK_NOT_COMPLETE", 409, "แมตช์วีคนี้ยังแข่งไม่ครบ")
            existing = await db.get(WeeklyReport, (season, matchweek))
            if existing and existing.status == "published":
                raise ServiceError("REPORT_ALREADY_PUBLISHED", 409, "รายงานนี้เผยแพร่แล้ว")
            scorers_row = await db.get(Scorers, season)
            match_data = [row.payload for row in matches]
            standings_data = standings.payload["rows"]
            scorers_data = scorers_row.payload["items"] if scorers_row else []
        try:
            response = await self.http.post(
                f"{self.settings.generation_url.rstrip('/')}/report/weekly",
                json={
                    "request_id": request_id,
                    "season": season,
                    "matchweek": matchweek,
                    "language": "th",
                    "matches": match_data,
                    "standings": standings_data,
                    "top_scorers": scorers_data,
                },
                headers={"X-Request-ID": request_id},
                timeout=60,
            )
            response.raise_for_status()
            generated = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ServiceError("UPSTREAM_UNAVAILABLE", 502, str(exc)) from exc
        payload = {
            "season": season,
            "matchweek": matchweek,
            "title": generated["title"],
            "markdown": generated["markdown"],
            "highlights": generated.get("highlights", []),
            "status": "draft",
            "generated_at": now_iso(),
            "data_as_of": min(row["fetched_at"] for row in match_data),
            "edited_at": None,
            "edited_by": None,
            "published_at": None,
            "published_by": None,
        }
        async with self.sessions() as db:
            await db.merge(
                WeeklyReport(season=season, matchweek=matchweek, status="draft", payload=payload)
            )
            await db.commit()
        if self.settings.report_auto_publish:
            await self.publish(season, matchweek, "beat", request_id)
