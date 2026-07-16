from collections.abc import Generator

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from auth import create_access_token, get_db, hash_password
from main import app
from models import Base, Meal, User, Workout


def make_test_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def empty_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = make_test_engine()
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr("main.init_db", lambda: None)
    monkeypatch.setattr("main.seed_test_user", lambda db: None)
    monkeypatch.setattr("main.seed_admin_user", lambda db: None)
    monkeypatch.setattr("main.recalculate_all_users_bmr", lambda db: None)
    monkeypatch.setattr("main.load_settings_from_db", lambda db: None)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        test_client.db_session = testing_session_local()
        yield test_client

    test_client.db_session.close()

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = make_test_engine()
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr("main.init_db", lambda: None)
    monkeypatch.setattr("main.seed_test_user", lambda db: None)
    monkeypatch.setattr("main.seed_admin_user", lambda db: None)
    monkeypatch.setattr("main.recalculate_all_users_bmr", lambda db: None)
    monkeypatch.setattr("main.load_settings_from_db", lambda db: None)
    app.dependency_overrides[get_db] = override_get_db

    db = testing_session_local()
    user = User(
        username="pytest_user",
        password_hash=hash_password("testpass"),
        name="Pytest User",
        gender="male",
        birth_date=date.today() - timedelta(days=365 * 30),
        height_cm=175.0,
        weight_kg=75.0,
        initial_weight_kg=75.0,
        bmr=1698.8,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    today = datetime.utcnow()
    db.add(
        Meal(
            user_id=user.id,
            food_name="Test oatmeal",
            calories=350.0,
            logged_at=today,
        )
    )
    db.add(
        Workout(
            user_id=user.id,
            activity_type="Test walk",
            calories_burned=150.0,
            logged_at=today,
        )
    )
    db.commit()

    auth_header = {"Authorization": f"Bearer {create_access_token(user)}"}

    with TestClient(app) as test_client:
        test_client.auth_headers = auth_header
        test_client.test_user = user
        test_client.db_session = db
        yield test_client

    db.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
