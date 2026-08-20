"""Declarative base for future SQLAlchemy models.

No models are defined in Phase 1.1 (only a connectivity check exists); this
attachment point lets later milestones add ORM models and Alembic
migrations without restructuring the database layer.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
