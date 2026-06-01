from app.texts.keys import TextKey


TEXTS_EN = {
    TextKey.START: {
        "text": (
            "{heart} Hi! I am TopSaver.\n\n"
            "I can help you download videos, photos and music from TikTok, YouTube, Instagram Reels and Pinterest.\n\n"
            "Choose your interface language:"
        ),
        "emoji": {"heart": "heart"},
    },

    TextKey.LANGUAGE_CHOOSE: {
        "text": "{globe} Choose your interface language.\n\nYou can change it anytime with /start.",
        "emoji": {"globe": "telegram"},
    },

    TextKey.LANGUAGE_SAVED: {
        "text": "{check} Language saved: {language_title}\n\nNow send me a link to a video, photo or music.",
        "emoji": {"check": "check"},
    },

    TextKey.LANGUAGE_REQUIRED: {
        "text": (
            "{warning} Choose your interface language before using the bot.\n\n"
            "After that I can show menus, quality options and audio tracks correctly."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.MY_ID: {
        "text": "{info} Your Telegram ID:\n`{user_id}`",
        "emoji": {"info": "info"},
        "code": ["user_id"],
    },

    TextKey.LINK_NO_URL: {
        "text": "{warning} I did not find a link in your message.\n\nSend a YouTube, TikTok, Instagram or Pinterest link.",
        "emoji": {"warning": "warning"},
    },

    TextKey.LINK_UNSUPPORTED: {
        "text": (
            "{warning} This platform is not supported yet.\n\n"
            "Currently supported:\n"
            "{youtube} YouTube / Shorts\n"
            "{tiktok} TikTok\n"
            "{instagram} Instagram\n"
            "{chain} Pinterest"
        ),
        "emoji": {
            "warning": "warning",
            "youtube": "youtube",
            "tiktok": "tiktok",
            "instagram": "instagram",
            "chain": "chain",
        },
    },

    TextKey.LINK_ACCEPTED: {
        "text": (
            "{download} Link accepted.\n\n"
            "Platform: {platform_title}\n"
            "URL: `{url}`\n\n"
            "{hourglass} Next we will add metadata, quality choice, audio tracks, cache and downloading."
        ),
        "emoji": {
            "download": "download",
            "hourglass": "hourglass",
        },
        "code": ["url"],
    },
    TextKey.LINK_ANALYZING: {
        "text": "{hourglass} Analyzing the link and reading media information...",
        "emoji": {"hourglass": "hourglass"},
    },

    TextKey.LINK_METADATA_FAILED: {
        "text": (
            "{warning} Could not read this link.\n\n"
            "The media may be private, deleted, or temporarily restricted by the platform."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ROUTE_DETECTED: {
        "text": (
            "{check} Link recognized.\n\n"
            "Platform: {platform}\n"
            "Type: {content_type}\n"
            "Action: {action}\n"
            "Title: `{title}`\n"
            "Duration: {duration}\n"
            "Entries: {entries_count}\n"
            "Photos: {photo_count}\n"
            "Videos: {video_count}\n"
            "Audio: {audio_count}\n"
            "Detected from: {media_detected_from}\n\n"
            "{hourglass} Next step: downloading."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_CHOOSE_QUALITY: {
        "text": (
            "{youtube} YouTube video found.\n\n"
            "Title: `{title}`\n"
            "Duration: {duration}\n\n"
            "Choose quality:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_QUALITY_SELECTED: {
        "text": (
            "{check} Quality selected: {quality_label}\n\n"
            "{hourglass} Next step: audio track selection and downloading."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_CHOOSE_AUDIO: {
        "text": (
            "{youtube} Quality selected: {quality_label}\n\n"
            "Title: `{title}`\n\n"
            "Choose audio track:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_AUDIO_SELECTED: {
        "text": (
            "{check} Audio selected: {audio_label}\n"
            "Quality: {quality_label}\n\n"
            "{hourglass} Next step: downloading the video."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Audio selected automatically: {audio_label}\n"
            "Quality: {quality_label}\n\n"
            "{hourglass} Next step: downloading the video."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.DOWNLOAD_STARTED: {
        "text": "{download} Starting download...",
        "emoji": {"download": "download"},
    },

    TextKey.DOWNLOAD_CACHE_HIT: {
        "text": "{check} Found the file in cache. Sending it without downloading again.",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_SUCCESS: {
        "text": "{check} Done. Files sent: {items_sent}/{items_total}",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_FAILED: {
        "text": (
            "{warning} Could not download or send this media.\n\n"
            "Reason: {error_text}"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ERROR_NO_TOKEN: {
        "text": "{error} BOT_TOKEN was not found.\n\nAdd BOT_TOKEN to nano.env.",
        "emoji": {"error": "error"},
    },

    TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO: {
        "text": (
            "{youtube} YouTube Shorts found.\n\n"
            "Title: `{title}`\n"
            "Duration: {duration}\n\n"
            "Choose audio track:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED: {
        "text": (
            "{check} Shorts audio selected: {audio_label}\n\n"
            "{hourglass} Starting download in maximum quality."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Shorts will be downloaded with original audio.\n\n"
            "{hourglass} Starting download in maximum quality."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },
}

TEXTS_EN.update({
    TextKey.ADD_TO_GROUP: {
        "text": "{telegram} You can now add this bot to a group and use it there.",
        "emoji": {"telegram": "telegram"},
    },
    TextKey.ADD_TO_GROUP_BUTTON: {
        "text": "Add bot to group",
    },
    TextKey.GROUP_WELCOME: {
        "text": "Ready to work in this group.\n\nSend /download link, /dl link{mention_hint}. You can also reply with a link to my message.",
    },
    TextKey.HELP_PROMPT: {
        "text": "{warning} Describe the problem in one message. I will send it to the admin.",
        "emoji": {"warning": "warning"},
    },
    TextKey.HELP_SENT: {
        "text": "{check} Thank you, I sent the problem to the admin.",
        "emoji": {"check": "check"},
    },
    TextKey.ACCESS_BANNED: {
        "text": "{stop} Access to the bot is restricted.",
        "emoji": {"stop": "stop"},
    },
    TextKey.ACCESS_UNAVAILABLE: {
        "text": "{warning} The bot is currently unavailable.",
        "emoji": {"warning": "warning"},
    },
    TextKey.ACCESS_DAILY_LIMIT: {
        "text": "{stop} Today's limit is reached: {daily_limit} downloads per day.\nTry again tomorrow.",
        "emoji": {"stop": "stop"},
    },
    TextKey.DOWNLOAD_PROCESSING_MEDIA: {
        "text": "{hourglass} Downloading media...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE: {
        "text": "{hourglass} Processing YouTube video...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE_MUSIC: {
        "text": "{music} Downloading YouTube Music...",
        "emoji": {"music": "music"},
    },
    TextKey.DOWNLOAD_PLATFORM_LIMITED: {
        "text": "{warning} {platform_title} temporarily limited access. This is temporary, do not worry, we will fix it soon.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_NETWORK: {
        "text": "{warning} Could not connect to the platform reliably. Try again a bit later.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_UNAVAILABLE: {
        "text": "{warning} Could not access this media. It may be private, deleted, or unavailable.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_GENERIC: {
        "text": "{warning} Could not download the media. Try another link or try again later.",
        "emoji": {"warning": "warning"},
    },
    TextKey.REQUIRED_SUBSCRIPTIONS_TEXT: {
        "text": "To use the bot, subscribe to the required resources below.\n\nAfter subscribing, press the check button.",
    },
    TextKey.REQUIRED_DONE: {
        "text": "{check} Done. You can now send links.",
        "emoji": {"check": "check"},
    },
    TextKey.REQUIRED_OPEN_PROMPT: {
        "text": "Open the resource using the button below, then come back and press the subscription check button.",
    },
    TextKey.REQUIRED_RESOURCE_NOT_FOUND: {
        "text": "Resource not found.",
    },
    TextKey.REQUIRED_URL_UNAVAILABLE: {
        "text": "Link is unavailable.",
    },
    TextKey.REQUIRED_URL_SENT: {
        "text": "Link sent.",
    },
    TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND: {
        "text": "Subscription was not found yet.",
    },
    TextKey.CALLBACK_INVALID_CHOICE: {
        "text": "Invalid choice.",
    },
    TextKey.CALLBACK_CHOICE_EXPIRED: {
        "text": "Choice expired. Send the link again.",
    },
    TextKey.CALLBACK_NOT_FOR_YOU: {
        "text": "This button is not for you.",
    },
    TextKey.YOUTUBE_AUDIO_MISSING: {
        "text": "This audio track is not available for this video. Choose Original or another language.",
    },
    TextKey.ERROR_INTERNAL: {
        "text": "{warning} Internal error. I have already saved it to the log.",
        "emoji": {"warning": "warning"},
    },
})
