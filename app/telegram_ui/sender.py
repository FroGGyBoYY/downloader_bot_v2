import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from telegram import MessageEntity
from telegram.error import NetworkError, TimedOut, TelegramError

from app.config import Settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentTelegramFile:
    file_id: str
    file_unique_id: Optional[str]
    send_type: str


def _extract_sent_file(message, send_type: str) -> SentTelegramFile:
    if send_type == "video" and message.video:
        return SentTelegramFile(
            file_id=message.video.file_id,
            file_unique_id=message.video.file_unique_id,
            send_type="video",
        )

    if send_type == "photo" and message.photo:
        largest = message.photo[-1]
        return SentTelegramFile(
            file_id=largest.file_id,
            file_unique_id=largest.file_unique_id,
            send_type="photo",
        )

    if send_type == "audio" and message.audio:
        return SentTelegramFile(
            file_id=message.audio.file_id,
            file_unique_id=message.audio.file_unique_id,
            send_type="audio",
        )

    if message.document:
        return SentTelegramFile(
            file_id=message.document.file_id,
            file_unique_id=message.document.file_unique_id,
            send_type="document",
        )

    raise RuntimeError("Telegram did not return file object")


async def send_cached_media(
    *,
    settings: Settings,
    bot,
    chat_id: int,
    tg_file_id: str,
    send_type: str,
    caption: str,
    caption_entities: Sequence[MessageEntity] | None = None,
    reply_to_message_id: int | None = None,
) -> SentTelegramFile:
    if send_type == "video":
        message = await bot.send_video(
            chat_id=chat_id,
            video=tg_file_id,
            caption=caption,
            caption_entities=caption_entities,
            supports_streaming=True,
            reply_to_message_id=reply_to_message_id,
            read_timeout=settings.send_read_timeout,
            write_timeout=settings.send_write_timeout,
            connect_timeout=settings.send_connect_timeout,
            pool_timeout=settings.send_pool_timeout,
        )
        return _extract_sent_file(message, "video")

    if send_type == "photo":
        message = await bot.send_photo(
            chat_id=chat_id,
            photo=tg_file_id,
            caption=caption,
            caption_entities=caption_entities,
            reply_to_message_id=reply_to_message_id,
            read_timeout=settings.send_read_timeout,
            write_timeout=settings.send_write_timeout,
            connect_timeout=settings.send_connect_timeout,
            pool_timeout=settings.send_pool_timeout,
        )
        return _extract_sent_file(message, "photo")

    if send_type == "audio":
        message = await bot.send_audio(
            chat_id=chat_id,
            audio=tg_file_id,
            caption=caption,
            caption_entities=caption_entities,
            reply_to_message_id=reply_to_message_id,
            read_timeout=settings.send_read_timeout,
            write_timeout=settings.send_write_timeout,
            connect_timeout=settings.send_connect_timeout,
            pool_timeout=settings.send_pool_timeout,
        )
        return _extract_sent_file(message, "audio")

    message = await bot.send_document(
        chat_id=chat_id,
        document=tg_file_id,
        caption=caption,
        caption_entities=caption_entities,
        reply_to_message_id=reply_to_message_id,
        read_timeout=settings.send_read_timeout,
        write_timeout=settings.send_write_timeout,
        connect_timeout=settings.send_connect_timeout,
        pool_timeout=settings.send_pool_timeout,
    )

    return _extract_sent_file(message, "document")


async def send_local_media(
    *,
    settings: Settings,
    bot,
    chat_id: int,
    file_path: Path,
    media_type: str,
    caption: str,
    caption_entities: Sequence[MessageEntity] | None = None,
    title: str | None = None,
    performer: str | None = None,
    duration: int | None = None,
    width: int | None = None,
    height: int | None = None,
    reply_to_message_id: int | None = None,
) -> SentTelegramFile:
    if media_type == "photo":
        with open(file_path, "rb") as f:
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=caption,
                caption_entities=caption_entities,
                reply_to_message_id=reply_to_message_id,
                read_timeout=settings.send_read_timeout,
                write_timeout=settings.send_write_timeout,
                connect_timeout=settings.send_connect_timeout,
                pool_timeout=settings.send_pool_timeout,
            )

        return _extract_sent_file(message, "photo")

    if media_type == "audio":
        with open(file_path, "rb") as f:
            message = await bot.send_audio(
                chat_id=chat_id,
                audio=f,
                caption=caption,
                caption_entities=caption_entities,
                title=title,
                performer=performer,
                duration=duration,
                reply_to_message_id=reply_to_message_id,
                read_timeout=settings.send_read_timeout,
                write_timeout=settings.send_write_timeout,
                connect_timeout=settings.send_connect_timeout,
                pool_timeout=settings.send_pool_timeout,
            )

        return _extract_sent_file(message, "audio")

    if media_type == "video":
        try:
            with open(file_path, "rb") as f:
                message = await bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=caption,
                    caption_entities=caption_entities,
                    supports_streaming=True,
                    width=width,
                    height=height,
                    duration=duration,
                    reply_to_message_id=reply_to_message_id,
                    read_timeout=settings.send_read_timeout,
                    write_timeout=settings.send_write_timeout,
                    connect_timeout=settings.send_connect_timeout,
                    pool_timeout=settings.send_pool_timeout,
                )

            return _extract_sent_file(message, "video")

        except (TimedOut, NetworkError, TelegramError) as e:
            logger.warning("send_video failed, fallback to document | file=%s | error=%s", file_path, e)

            with open(file_path, "rb") as f:
                message = await bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=caption,
                    caption_entities=caption_entities,
                    reply_to_message_id=reply_to_message_id,
                    read_timeout=settings.send_read_timeout,
                    write_timeout=settings.send_write_timeout,
                    connect_timeout=settings.send_connect_timeout,
                    pool_timeout=settings.send_pool_timeout,
                )

            return _extract_sent_file(message, "document")

    with open(file_path, "rb") as f:
        message = await bot.send_document(
            chat_id=chat_id,
            document=f,
            caption=caption,
            caption_entities=caption_entities,
            reply_to_message_id=reply_to_message_id,
            read_timeout=settings.send_read_timeout,
            write_timeout=settings.send_write_timeout,
            connect_timeout=settings.send_connect_timeout,
            pool_timeout=settings.send_pool_timeout,
        )

    return _extract_sent_file(message, "document")
