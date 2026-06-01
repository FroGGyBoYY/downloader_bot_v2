from dataclasses import dataclass
from typing import Optional


@dataclass
class DownloadJob:
    request_id: int
    chat_id: int
    user_id: int
    username: Optional[str]
    full_name: str
    url: str
    message_id: Optional[int] = None
    requested_quality: Optional[int] = None
    requested_audio_lang: Optional[str] = None
    cleanup_message_id: Optional[int] = None


@dataclass(frozen=True)
class DetectedLink:
    url: str
    platform: str
    host: str