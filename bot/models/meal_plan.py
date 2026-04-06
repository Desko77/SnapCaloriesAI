from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    period_type: Mapped[str] = mapped_column(String(10))  # day / week / month
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    days: Mapped[list["MealPlanDay"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_meal_plans_user_active", "user_id", "is_active"),
    )


class MealPlanDay(Base):
    __tablename__ = "meal_plan_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id"), nullable=False)

    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    calories: Mapped[float] = mapped_column(Float, default=0)
    protein: Mapped[float] = mapped_column(Float, default=0)
    fat: Mapped[float] = mapped_column(Float, default=0)
    carbs: Mapped[float] = mapped_column(Float, default=0)
    meals_json: Mapped[str | None] = mapped_column(Text)

    plan: Mapped["MealPlan"] = relationship(back_populates="days")

    __table_args__ = (
        Index("ix_meal_plan_days_plan_date", "plan_id", "day_date"),
    )
