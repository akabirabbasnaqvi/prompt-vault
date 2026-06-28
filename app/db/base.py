"""
app/db/base.py

The SQLAlchemy declarative base.

SKILL: SQLAlchemy ORM
WHY: Every database table we define (prompts, users, evaluations)
     will inherit from this Base class. SQLAlchemy uses this to:
     - Know which classes represent database tables
     - Track all table definitions for Alembic migrations
     - Provide ORM features (relationships, lazy loading, etc.)

Think of Base as the "parent class of all database tables."
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    Every table in PromptVault will be defined like:

        class Prompt(Base):
            __tablename__ = "prompts"
            id = mapped_column(Integer, primary_key=True)
            ...

    By inheriting from Base, SQLAlchemy knows this class
    represents a database table and should be managed by
    Alembic for migrations.
    """
    pass