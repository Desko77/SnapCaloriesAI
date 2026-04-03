from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        event_user = data.get("event_from_user")

        if session and event_user:
            result = await session.execute(
                select(User).where(User.telegram_id == event_user.id)
            )
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    telegram_id=event_user.id,
                    username=event_user.username,
                    first_name=event_user.first_name or "",
                    last_name=event_user.last_name,
                )
                session.add(user)
            else:
                user.username = event_user.username
                user.first_name = event_user.first_name or ""
                user.last_name = event_user.last_name

            await session.commit()
            data["user"] = user

        return await handler(event, data)
