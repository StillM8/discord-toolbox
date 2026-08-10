"""SQLAlchemy persistence models; these never leave the storage layer."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for the local persistence adapter."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetime round-trips to aware UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SavedItemRow(Base):
    __tablename__ = "saved_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    asset_mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    asset_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContextItemRow(Base):
    __tablename__ = "context_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(500))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_data: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    asset_mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    asset_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PreferenceRow(Base):
    __tablename__ = "user_preferences"

    owner_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    language: Mapped[str] = mapped_column(String(100), default="English")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    default_profile: Mapped[str] = mapped_column(String(20), default="normal")
    quote_font: Mapped[str] = mapped_column(String(20), default="sans")
    quote_text_position: Mapped[str] = mapped_column(String(20), default="center")
    quote_color_mode: Mapped[str] = mapped_column(String(20), default="grayscale")
    quote_image_mode: Mapped[str] = mapped_column(String(20), default="left")
    accessibility_plain_text: Mapped[bool] = mapped_column(default=False)
    accessibility_high_contrast: Mapped[bool] = mapped_column(default=False)
    accessibility_reduce_motion: Mapped[bool] = mapped_column(default=False)
    accessibility_verbose: Mapped[bool] = mapped_column(default=False)


class ReminderRow(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    due_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InteractionSessionRow(Base):
    __tablename__ = "interaction_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict[str, str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
