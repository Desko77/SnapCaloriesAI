SIGNAL_ICONS = {
    "green": "[G]",
    "yellow": "[Y]",
    "red": "[R]",
}


def format_signal(level: str, text: str) -> str:
    icon = SIGNAL_ICONS.get(level, "[?]")
    return f"{icon} {text}"


def format_progress_bar(current: float, goal: float, width: int = 10) -> str:
    if goal <= 0:
        return "[" + "-" * width + "] 0%"
    ratio = min(current / goal, 1.0)
    filled = int(ratio * width)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {int(ratio * 100)}%"


def format_macros(calories: float, protein: float, fat: float, carbs: float) -> str:
    return (
        f"Калории: {calories:.0f} ккал\n"
        f"Белки: {protein:.0f} г\n"
        f"Жиры: {fat:.0f} г\n"
        f"Углеводы: {carbs:.0f} г"
    )
