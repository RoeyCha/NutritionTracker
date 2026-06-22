from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATABASE_URL = "sqlite:///./nutrition_tracker.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr_explanation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    meals: Mapped[list["Meal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    workouts: Mapped[list["Workout"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    daily_steps: Mapped[list["DailySteps"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    food_name: Mapped[str] = mapped_column(String(200), nullable=False)
    calories: Mapped[float] = mapped_column(Float, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["User"] = relationship(back_populates="meals")


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(200), nullable=False)
    calories_burned: Mapped[float] = mapped_column(Float, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["User"] = relationship(back_populates="workouts")


class DailySteps(Base):
    __tablename__ = "daily_steps"
    __table_args__ = (UniqueConstraint("user_id", "entry_date", name="uq_user_steps_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    steps_count: Mapped[int] = mapped_column(Integer, nullable=False)
    calories_burned: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_explanation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="daily_steps")


def migrate_db() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    statements = []

    if "username" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN username VARCHAR(50)")
    if "password_hash" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
    if "gender" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN gender VARCHAR(20)")
    if "age" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN age INTEGER")
    if "weight_kg" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN weight_kg FLOAT")
    if "bmr" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN bmr FLOAT")
    if "bmr_explanation" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN bmr_explanation VARCHAR(500)")

    if not statements and "username" in columns and "password_hash" in columns:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

        if "username" in {column["name"] for column in inspect(engine).get_columns("users")}:
            connection.execute(
                text(
                    "UPDATE users SET username = lower(substr(email, 1, instr(email, '@') - 1)) "
                    "WHERE username IS NULL AND email IS NOT NULL"
                )
            )
            connection.execute(
                text("UPDATE users SET username = 'user_' || id WHERE username IS NULL")
            )
        if "password_hash" in {column["name"] for column in inspect(engine).get_columns("users")}:
            connection.execute(
                text("UPDATE users SET password_hash = '' WHERE password_hash IS NULL")
            )


def init_db() -> None:
    migrate_db()
    Base.metadata.create_all(bind=engine)
