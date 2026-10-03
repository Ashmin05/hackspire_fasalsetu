"""Declarative base shared by all ORM models. Alembic autogenerate reads its metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
