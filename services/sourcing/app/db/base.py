"""
AHP Sourcing Engine — SQLAlchemy declarative base.

All ORM models inherit from :class:`Base` so that Alembic can discover them
through a single ``target_metadata`` reference.

Usage::

    from app.db.base import Base

    class MyModel(Base):
        __tablename__ = "my_table"
        ...
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Shared declarative base for every SQLAlchemy model in the sourcing service.

    Provides:
    * ``id`` — a UUID primary key generated server-side.
    * ``created_at`` / ``updated_at`` — automatic timestamp bookkeeping.
    """

    # Common columns inherited by every table
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="Primary key (UUID v4).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        comment="Row creation timestamp (UTC).",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Last update timestamp (UTC).",
    )
