import logging
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic_ns
from typing import Optional, Sequence

from telegram import MessageEntity
from telegram.error import NetworkError, TimedOut, TelegramError

from app.config import Settings


logger = logging.getLogger(__name__)


LARGE_VIDEO_FALLBACK_LIMIT = 50 * 1024 * 1024
LOCAL_BOT_API_SHARED_ROOT = Path("/var/lib/telegram-bot-api/codex_uploads")


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


def _is_large_uncertain_send_error(file_path: Path, error: Exception) -> bool:
    if not isinstance(error, (TimedOut, NetworkError)):
        return False

    try:
        return file_path.stat().st_size >= LARGE_VIDEO_FALLBACK_LIMIT
    except Exception:
        return True


@contextmanager
def _prepared_upload_file(settings: Settings, file_path: Path):
    if not settings.use_local_bot_api:
        with open(file_path, "rb") as f:
            yield f
        return

    staged_path: Path | None = None
    try:
        LOCAL_BOT_API_SHARED_ROOT.mkdir(parents=True, exist_ok=True)
        staged_path = LOCAL_BOT_API_SHARED_ROOT / f"{os.getpid()}_{monotonic_ns()}_{file_path.name}"
        try:
            os.link(file_path, staged_path)
        except OSError:
            shutil.copy2(file_path, staged_path)

        yield staged_path
    except Exception as e:
        logger.warning(
            "Local Bot API shared file path unavailable, streaming upload | file=%s error=%s",
            file_path,
            e,
        )
        with open(file_path, "rb") as f:
            yield f
    finally:
        if staged_path:
            try:
                staged_path.unlink(missing_ok=True)
            except Exception:
                logger.exception("Could not remove staged Telegram upload file | path=%s", staged_path)


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
        with _prepared_upload_file(settings, file_path) as upload_file:
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=upload_file,
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
        with _prepared_upload_file(settings, file_path) as upload_file:
            message = await bot.send_audio(
                chat_id=chat_id,
                audio=upload_file,
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
            with _prepared_upload_file(settings, file_path) as upload_file:
                message = await bot.send_video(
                    chat_id=chat_id,
                    video=upload_file,
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
            if _is_large_uncertain_send_error(file_path, e):
                logger.warning(
                    "send_video failed after large upload, skip document fallback to avoid duplicate | file=%s size=%s error=%s",
                    file_path,
                    file_path.stat().st_size if file_path.exists() else None,
                    e,
                )
                raise

            logger.warning("send_video failed, fallback to document | file=%s | error=%s", file_path, e)

            with _prepared_upload_file(settings, file_path) as upload_file:
                message = await bot.send_document(
                    chat_id=chat_id,
                    document=upload_file,
                    caption=caption,
                    caption_entities=caption_entities,
                    reply_to_message_id=reply_to_message_id,
                    read_timeout=settings.send_read_timeout,
                    write_timeout=settings.send_write_timeout,
                    connect_timeout=settings.send_connect_timeout,
                    pool_timeout=settings.send_pool_timeout,
                )

            return _extract_sent_file(message, "document")

    with _prepared_upload_file(settings, file_path) as upload_file:
        message = await bot.send_document(
            chat_id=chat_id,
            document=upload_file,
            caption=caption,
            caption_entities=caption_entities,
            reply_to_message_id=reply_to_message_id,
            read_timeout=settings.send_read_timeout,
            write_timeout=settings.send_write_timeout,
            connect_timeout=settings.send_connect_timeout,
            pool_timeout=settings.send_pool_timeout,
        )

    return _extract_sent_file(message, "document")
