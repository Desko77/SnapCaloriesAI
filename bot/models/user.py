from datetime import date, datetime

from sqlalchemy import BigInteger, Date, Float, String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str | None] = mapped_column(String(255))

    age: Mapped[int | None] = mapped_column(Integer)
    gender: Mapped[str | None] = mapped_column(String(10))  # male / female
    weight: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    activity_level: Mapped[str | None] = mapped_column(String(20))  # sedentary / light / moderate / active / athlete
    activity_description: Mapped[str | None] = mapped_column(String(500))  # свободное описание
    target_weight: Mapped[float | None] = mapped_column(Float)
    goal_type: Mapped[str] = mapped_column(String(20), default="maintain")
    goal_deadline: Mapped[date | None] = mapped_column(Date)

    daily_calories_goal: Mapped[int] = mapped_column(Integer, default=2000)
    daily_protein_goal: Mapped[int] = mapped_column(Integer, default=120)
    daily_fat_goal: Mapped[int] = mapped_column(Integer, default=65)
    daily_carbs_goal: Mapped[int] = mapped_column(Integer, default=250)

    response_mode: Mapped[str] = mapped_column(String(20), default="compact")
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    meals: Mapped[list["MealLog"]] = relationship(back_populates="user")


from bot.models.meal import MealLog  # noqa: E402
