import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

logger = logging.getLogger(__name__)


class AlbumMiddleware(BaseMiddleware):
    """Collects photos from a Telegram media group (album) into a single handler call.

    When a user sends multiple photos at once, Telegram delivers them as
    separate Message updates sharing the same media_group_id. This middleware
    buffers those messages for `latency` seconds, then passes all collected
    messages as data["album"] to the handler of the *first* message only.
    Subsequent messages in the group are silently consumed.
    """

    def __init__(self, latency: float = 0.7):
        super().__init__()
        self.latency = latency
        self._albums: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        group_id = event.media_group_id

        if group_id not in self._albums:
            # first message in the group - create buffer, wait, then process
            self._albums[group_id] = [event]
            await asyncio.sleep(self.latency)

            album = self._albums.pop(group_id, [event])
            # sort by message_id to preserve order
            album.sort(key=lambda m: m.message_id)

            logger.info(
                "Album %s: collected %d photo(s), caption=%r",
                group_id, len(album), album[0].caption,
            )
            data["album"] = album
            return await handler(event, data)
        else:
            # subsequent message - just append to buffer, do NOT call handler
            self._albums[group_id].append(event)
            return None
