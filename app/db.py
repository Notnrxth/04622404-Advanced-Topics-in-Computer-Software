"""Persistent football snapshots. Only this service writes the football schema."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, MetaData, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def schema_for(url: str) -> str | None:
    return None if url.startswith("sqlite") else "football"


class Base(DeclarativeBase):
    metadata = MetaData(schema="football")


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(4), index=True)
    matchweek: Mapped[int | None] = mapped_column(Integer, index=True)
    home_team_id: Mapped[int] = mapped_column(Integer, index=True)
    away_team_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Standing(Base):
    __tablename__ = "standings"

    season: Mapped[str] = mapped_column(String(4), primary_key=True)
    matchweek: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Scorers(Base):
    __tablename__ = "scorers"

    season: Mapped[str] = mapped_column(String(4), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    triggered_by: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"

    season: Mapped[str] = mapped_column(String(4), primary_key=True)
    matchweek: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ServiceState(Base):
    __tablename__ = "service_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


def make_database(url: str):
    # SQLite does not support schemas; translate this service's schema for local development.
    options = {"schema_translate_map": {"football": None}} if schema_for(url) is None else {}
    engine = create_async_engine(url, pool_pre_ping=True, execution_options=options)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, sessions
