from aiogram.fsm.state import State, StatesGroup


class RefineState(StatesGroup):
    waiting_for_text = State()


class GoalEditState(StatesGroup):
    waiting_for_value = State()
