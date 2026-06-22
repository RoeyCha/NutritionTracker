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
    initial_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr_explanation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    meals: Mapped[list["Meal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    workouts: Mapped[list["Workout"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    daily_steps: Mapped[list["DailySteps"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    daily_weights: Mapped[list["DailyWeight"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    food_name: Mapped[str] = mapped_column(String(200), nullable=False)
    calories: Mapped[float] = mapped_column(Float, nullable=False)
    protein: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    carbohydrates: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fats: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
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


class DailyWeight(Base):
    __tablename__ = "daily_weights"
    __table_args__ = (UniqueConstraint("user_id", "entry_date", name="uq_user_weight_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="daily_weights")


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
    if "initial_weight_kg" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN initial_weight_kg FLOAT")
    if "bmr" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN bmr FLOAT")
    if "bmr_explanation" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN bmr_explanation VARCHAR(500)")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

            updated_columns = {column["name"] for column in inspect(engine).get_columns("users")}
            if "username" in updated_columns:
                connection.execute(
                    text(
                        "UPDATE users SET username = lower(substr(email, 1, instr(email, '@') - 1)) "
                        "WHERE username IS NULL AND email IS NOT NULL"
                    )
                )
                connection.execute(
                    text("UPDATE users SET username = 'user_' || id WHERE username IS NULL")
                )
            if "password_hash" in updated_columns:
                connection.execute(
                    text("UPDATE users SET password_hash = '' WHERE password_hash IS NULL")
                )
            if "initial_weight_kg" in updated_columns:
                connection.execute(
                    text(
                        "UPDATE users SET initial_weight_kg = weight_kg "
                        "WHERE initial_weight_kg IS NULL AND weight_kg IS NOT NULL"
                    )
                )

    if _users_email_not_nullable():
        with engine.begin() as connection:
            _rebuild_users_table(connection)

    _migrate_meals_macros()


def _migrate_meals_macros() -> None:
    inspector = inspect(engine)
    if "meals" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("meals")}
    statements = []
    for column_name in ("protein", "carbohydrates", "fats"):
        if column_name not in columns:
            statements.append(f"ALTER TABLE meals ADD COLUMN {column_name} FLOAT DEFAULT 0.0")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _users_email_not_nullable() -> bool:
    with engine.connect() as connection:
        rows = connection.execute(text("PRAGMA table_info(users)")).fetchall()
    email_row = next((row for row in rows if row[1] == "email"), None)
    return email_row is not None and bool(email_row[3])


def _rebuild_users_table(connection) -> None:
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(
        text(
            """
            CREATE TABLE users__new (
                id INTEGER PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(255) UNIQUE,
                gender VARCHAR(20),
                age INTEGER,
                weight_kg FLOAT,
                initial_weight_kg FLOAT,
                bmr FLOAT,
                bmr_explanation VARCHAR(500),
                created_at DATETIME NOT NULL
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO users__new (
                id, username, password_hash, name, email, gender, age, weight_kg,
                initial_weight_kg, bmr, bmr_explanation, created_at
            )
            SELECT
                id,
                COALESCE(username, 'user_' || id),
                COALESCE(password_hash, ''),
                name,
                NULLIF(email, ''),
                gender,
                age,
                weight_kg,
                initial_weight_kg,
                bmr,
                bmr_explanation,
                created_at
            FROM users
            """
        )
    )
    connection.execute(text("DROP TABLE users"))
    connection.execute(text("ALTER TABLE users__new RENAME TO users"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_id ON users (id)"))
    connection.execute(text("PRAGMA foreign_keys=ON"))


def init_db() -> None:
    migrate_db()
    Base.metadata.create_all(bind=engine)
