"""Generate calorie trend charts as PNG images."""

import io
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def generate_trend_chart(
    daily_breakdown: list[dict],
    calories_goal: int,
    period_label: str = "Неделя",
) -> bytes:
    """Generate a calories trend chart and return PNG bytes."""
    days = []
    calories = []
    proteins = []

    for d in daily_breakdown:
        day = d["day"]
        if isinstance(day, str):
            parts = day.split(".")
            day = date(2026, int(parts[1]), int(parts[0]))
        days.append(day)
        calories.append(d["calories"])
        proteins.append(d.get("protein", 0))

    fig, ax = plt.subplots(figsize=(8, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    # Calorie bars
    colors = ["#e94560" if c > calories_goal else "#0f3460" for c in calories]
    bars = ax.bar(days, calories, color=colors, width=0.6, alpha=0.85, label="Калории")

    # Goal line
    ax.axhline(y=calories_goal, color="#00d2ff", linestyle="--", linewidth=2,
               label=f"Цель: {calories_goal} ккал", alpha=0.8)

    # Value labels on bars
    for bar, cal in zip(bars, calories):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 20,
                f"{int(cal)}", ha="center", va="bottom", fontsize=9,
                color="white", fontweight="bold")

    # Styling
    ax.set_ylabel("ккал", color="white", fontsize=12)
    ax.set_title(f"Калории за {period_label.lower()}", color="white",
                 fontsize=14, fontweight="bold", pad=10)
    ax.legend(loc="upper right", facecolor="#16213e", edgecolor="gray",
              labelcolor="white", fontsize=9)

    ax.tick_params(colors="white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("gray")
    ax.spines["bottom"].set_color("gray")

    # X-axis: weekday + date
    def fmt_day(d):
        wd = WEEKDAYS_RU[d.weekday()]
        return f"{wd}\n{d.strftime('%d.%m')}"

    ax.set_xticks(days)
    ax.set_xticklabels([fmt_day(d) for d in days], fontsize=9, color="white")

    # Y range
    max_cal = max(max(calories), calories_goal) if calories else calories_goal
    ax.set_ylim(0, max_cal * 1.2)

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
