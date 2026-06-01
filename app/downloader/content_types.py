from enum import Enum


class Platform(str, Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    PINTEREST = "pinterest"
    UNKNOWN = "unknown"


class ContentType(str, Enum):
    VIDEO = "video"
    SHORTS = "shorts"
    REEL = "reel"

    PHOTO = "photo"
    PHOTO_ALBUM = "photo_album"
    MIXED_ALBUM = "mixed_album"

    POST = "post"
    PIN = "pin"
    STORY = "story"
    AUDIO = "audio"
    MUSIC_PAGE = "music_page"

    UNKNOWN = "unknown"


class DownloadAction(str, Enum):
    DOWNLOAD_VIDEO_MAX = "download_video_max"
    ASK_YOUTUBE_QUALITY = "ask_youtube_quality"

    DOWNLOAD_AUDIO = "download_audio"
    DOWNLOAD_PHOTO = "download_photo"
    DOWNLOAD_ALBUM = "download_album"
    DOWNLOAD_STORY = "download_story"

    UNSUPPORTED = "unsupported"