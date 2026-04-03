SIGNAL_ICONS = {
    "green": "\u2705",   # white check mark
    "yellow": "\u26a0\ufe0f",  # warning
    "red": "\u274c",     # cross mark
}


def format_signal(level: str, text: str) -> str:
    icon = SIGNAL_ICONS.get(level, "\u2753")
    return f"{icon} {text}"


def format_progress_bar(current: float, goal: float, width: int = 10) -> str:
    if goal <= 0:
        return "\u25ab" * width + " 0%"
    ratio = min(current / goal, 1.0)
    filled = int(ratio * width)
    bar = "\u25fc" * filled + "\u25fb" * (width - filled)
    pct = int(ratio * 100)
    if pct >= 90:
        emoji = "\U0001f525"  # fire
    elif pct >= 50:
        emoji = "\U0001f4aa"  # bicep
    else:
        emoji = "\U0001f3af"  # target
    return f"{bar} {pct}% {emoji}"


def format_macros(calories: float, protein: float, fat: float, carbs: float) -> str:
    return (
        f"\U0001f525 Калории: {calories:.0f} ккал\n"
        f"\U0001f4aa Белки: {protein:.0f} г\n"
        f"\U0001f9c8 Жиры: {fat:.0f} г\n"
        f"\U0001f33e Углеводы: {carbs:.0f} г"
    )


def format_macros_range(
    cal_min: float, cal_max: float,
    pro_min: float, pro_max: float,
    fat_min: float, fat_max: float,
    carb_min: float, carb_max: float,
) -> str:
    def r(lo, hi):
        if lo == hi:
            return str(int(lo))
        return f"{int(lo)}-{int(hi)}"

    return (
        f"\U0001f525 Калории: {r(cal_min, cal_max)} ккал\n"
        f"\U0001f4aa Белки: {r(pro_min, pro_max)} г\n"
        f"\U0001f9c8 Жиры: {r(fat_min, fat_max)} г\n"
        f"\U0001f33e Углеводы: {r(carb_min, carb_max)} г"
    )
