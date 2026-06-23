import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models
from models import Base, User, migrate_db


def _legacy_users_schema(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL,
                username VARCHAR(50),
                password_hash VARCHAR(255)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO users (id, name, email, created_at, username, password_hash)
            VALUES (1, 'Legacy User', 'legacy@example.com', '2026-01-01 00:00:00', 'legacy', 'hash')
            """
        )
    )


def test_migrate_db_makes_email_nullable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "legacy.db"
    legacy_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )

    with legacy_engine.begin() as connection:
        _legacy_users_schema(connection)

    monkeypatch.setattr(models, "engine", legacy_engine)
    monkeypatch.setattr(
        models,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=legacy_engine),
    )

    migrate_db()

    with sqlite3.connect(db_file) as connection:
        email_column = next(
            row for row in connection.execute("PRAGMA table_info(users)") if row[1] == "email"
        )
        assert email_column[3] == 0

        connection.execute(
            """
            INSERT INTO users (username, password_hash, name, email, created_at)
            VALUES ('new_user', 'hash', 'New User', NULL, '2026-06-22 00:00:00')
            """
        )
        row = connection.execute(
            "SELECT email FROM users WHERE username = 'new_user'"
        ).fetchone()
        assert row[0] is None


def test_migrate_db_preserves_existing_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "legacy.db"
    legacy_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )

    with legacy_engine.begin() as connection:
        _legacy_users_schema(connection)

    monkeypatch.setattr(models, "engine", legacy_engine)
    monkeypatch.setattr(
        models,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=legacy_engine),
    )

    migrate_db()

    session = sessionmaker(autocommit=False, autoflush=False, bind=legacy_engine)()
    try:
        user = session.query(User).filter(User.username == "legacy").one()
        assert user.email == "legacy@example.com"
        assert user.name == "Legacy User"
    finally:
        session.close()


def test_migrate_db_adds_birth_date_and_height_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "profile_fields.db"
    legacy_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )

    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(255),
                    gender VARCHAR(20),
                    age INTEGER,
                    weight_kg FLOAT,
                    bmr FLOAT,
                    bmr_explanation VARCHAR(500),
                    created_at DATETIME NOT NULL
                )
                """
            )
        )

    monkeypatch.setattr(models, "engine", legacy_engine)
    monkeypatch.setattr(
        models,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=legacy_engine),
    )

    migrate_db()
    Base.metadata.create_all(bind=legacy_engine)

    with sqlite3.connect(db_file) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert "birth_date" in columns
        assert "height_cm" in columns
