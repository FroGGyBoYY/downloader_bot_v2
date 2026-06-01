from app.texts.keys import TextKey


TEXTS_ZH = {
    TextKey.START: {
        "text": (
            "{heart} 你好！我是 TopSaver。\n\n"
            "我可以帮助你从 TikTok、YouTube、Instagram Reels 和 Pinterest 下载视频、照片和音乐。\n\n"
            "请选择界面语言："
        ),
        "emoji": {"heart": "heart"},
    },

    TextKey.LANGUAGE_CHOOSE: {
        "text": "{globe} 请选择界面语言。\n\n你可以随时通过 /start 更改语言。",
        "emoji": {"globe": "telegram"},
    },

    TextKey.LANGUAGE_SAVED: {
        "text": "{check} 语言已保存：{language_title}\n\n现在发送视频、照片或音乐链接给我。",
        "emoji": {"check": "check"},
    },

    TextKey.LANGUAGE_REQUIRED: {
        "text": (
            "{warning} 使用机器人前，请先选择界面语言。\n\n"
            "之后我就可以正确显示菜单、画质选项和音轨。"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.MY_ID: {
        "text": "{info} 你的 Telegram ID：\n`{user_id}`",
        "emoji": {"info": "info"},
        "code": ["user_id"],
    },

    TextKey.LINK_NO_URL: {
        "text": "{warning} 我没有在消息中找到链接。\n\n请发送 YouTube、TikTok、Instagram 或 Pinterest 链接。",
        "emoji": {"warning": "warning"},
    },

    TextKey.LINK_UNSUPPORTED: {
        "text": (
            "{warning} 目前还不支持这个平台。\n\n"
            "现在支持：\n"
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
            "{download} 链接已接收。\n\n"
            "平台：{platform_title}\n"
            "链接：`{url}`\n\n"
            "{hourglass} 下一步我们会添加 metadata、画质选择、音轨、缓存和下载功能。"
        ),
        "emoji": {
            "download": "download",
            "hourglass": "hourglass",
        },
        "code": ["url"],
    },

        TextKey.LINK_ANALYZING: {
        "text": "{hourglass} 正在分析链接并读取媒体信息...",
        "emoji": {"hourglass": "hourglass"},
    },

    TextKey.LINK_METADATA_FAILED: {
        "text": (
            "{warning} 无法读取此链接。\n\n"
            "该媒体可能是私密内容、已被删除，或平台暂时限制了访问。"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ROUTE_DETECTED: {
        "text": (
            "{check} 链接已识别。\n\n"
            "平台：{platform}\n"
            "类型：{content_type}\n"
            "操作：{action}\n"
            "标题：`{title}`\n"
            "时长：{duration}\n"
            "项目数量：{entries_count}\n\n"
            "{hourglass} 下一步：下载。"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_CHOOSE_QUALITY: {
        "text": (
            "{youtube} 已找到 YouTube 视频。\n\n"
            "标题：`{title}`\n"
            "时长：{duration}\n\n"
            "请选择画质："
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_QUALITY_SELECTED: {
        "text": (
            "{check} 已选择画质：{quality_label}\n\n"
            "{hourglass} 下一步：选择音轨并下载。"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

 TextKey.YOUTUBE_CHOOSE_AUDIO: {
        "text": (
            "{youtube} 已选择画质：{quality_label}\n\n"
            "标题：`{title}`\n\n"
            "请选择音轨："
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_AUDIO_SELECTED: {
        "text": (
            "{check} 已选择音轨：{audio_label}\n"
            "画质：{quality_label}\n\n"
            "{hourglass} 下一步：下载视频。"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} 已自动选择音轨：{audio_label}\n"
            "画质：{quality_label}\n\n"
            "{hourglass} 下一步：下载视频。"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.DOWNLOAD_STARTED: {
        "text": "{download} 开始下载...",
        "emoji": {"download": "download"},
    },

    TextKey.DOWNLOAD_CACHE_HIT: {
        "text": "{check} 已在缓存中找到文件。无需重新下载，正在发送。",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_SUCCESS: {
        "text": "{check} 完成。已发送文件：{items_sent}/{items_total}",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_FAILED: {
        "text": (
            "{warning} 无法下载或发送此媒体。\n\n"
            "原因：{error_text}"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ERROR_NO_TOKEN: {
        "text": "{error} 未找到 BOT_TOKEN。\n\n请将 BOT_TOKEN 添加到 nano.env。",
        "emoji": {"error": "error"},
    },

    TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO: {
        "text": (
            "{youtube} 已找到 YouTube Shorts。\n\n"
            "标题：`{title}`\n"
            "时长：{duration}\n\n"
            "请选择音轨："
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED: {
        "text": (
            "{check} Shorts 音轨已选择：{audio_label}\n\n"
            "{hourglass} 开始以最高画质下载。"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Shorts 将使用原始音频下载。\n\n"
            "{hourglass} 开始以最高画质下载。"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

}

TEXTS_ZH.update({
    TextKey.ADD_TO_GROUP: {
        "text": "{telegram} 现在可以把这个机器人添加到群组中使用。",
        "emoji": {"telegram": "telegram"},
    },
    TextKey.ADD_TO_GROUP_BUTTON: {
        "text": "添加机器人到群组",
    },
    TextKey.GROUP_WELCOME: {
        "text": "我已经可以在这个群组中工作。\n\n发送 /download 链接、/dl 链接{mention_hint}。也可以回复我的消息并附上链接。",
    },
    TextKey.HELP_PROMPT: {
        "text": "{warning} 请用一条消息描述问题。我会发送给管理员。",
        "emoji": {"warning": "warning"},
    },
    TextKey.HELP_SENT: {
        "text": "{check} 谢谢，我已把问题发送给管理员。",
        "emoji": {"check": "check"},
    },
    TextKey.ACCESS_BANNED: {
        "text": "{stop} 你访问此机器人的权限受限。",
        "emoji": {"stop": "stop"},
    },
    TextKey.ACCESS_UNAVAILABLE: {
        "text": "{warning} 机器人暂时不可用。",
        "emoji": {"warning": "warning"},
    },
    TextKey.ACCESS_DAILY_LIMIT: {
        "text": "{stop} 今天的限额已用完：每天 {daily_limit} 次下载。\n请明天再试。",
        "emoji": {"stop": "stop"},
    },
    TextKey.DOWNLOAD_PROCESSING_MEDIA: {
        "text": "{hourglass} 正在下载媒体...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE: {
        "text": "{hourglass} 正在处理 YouTube 视频...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE_MUSIC: {
        "text": "{music} 正在下载 YouTube Music...",
        "emoji": {"music": "music"},
    },
    TextKey.DOWNLOAD_PLATFORM_LIMITED: {
        "text": "{warning} {platform_title} 暂时限制了访问。这是临时问题，不用担心，我们会尽快处理。",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_NETWORK: {
        "text": "{warning} 无法稳定连接到平台。请稍后再试。",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_UNAVAILABLE: {
        "text": "{warning} 无法获取此媒体。它可能是私密、已删除或不可用。",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_GENERIC: {
        "text": "{warning} 无法下载媒体。请尝试其他链接或稍后重试。",
        "emoji": {"warning": "warning"},
    },
    TextKey.REQUIRED_SUBSCRIPTIONS_TEXT: {
        "text": "要使用机器人，请先订阅下面的必需资源。\n\n订阅后请点击检查按钮。",
    },
    TextKey.REQUIRED_DONE: {
        "text": "{check} 完成。现在可以发送链接了。",
        "emoji": {"check": "check"},
    },
    TextKey.REQUIRED_OPEN_PROMPT: {
        "text": "请用下面的按钮打开资源，然后回来点击订阅检查。",
    },
    TextKey.REQUIRED_RESOURCE_NOT_FOUND: {
        "text": "未找到资源。",
    },
    TextKey.REQUIRED_URL_UNAVAILABLE: {
        "text": "链接不可用。",
    },
    TextKey.REQUIRED_URL_SENT: {
        "text": "链接已发送。",
    },
    TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND: {
        "text": "暂未找到订阅。",
    },
    TextKey.CALLBACK_INVALID_CHOICE: {
        "text": "选择无效。",
    },
    TextKey.CALLBACK_CHOICE_EXPIRED: {
        "text": "选择已过期。请重新发送链接。",
    },
    TextKey.CALLBACK_NOT_FOR_YOU: {
        "text": "这个按钮不是给你的。",
    },
    TextKey.YOUTUBE_AUDIO_MISSING: {
        "text": "此视频没有这个音轨。请选择 Original 或其他语言。",
    },
    TextKey.ERROR_INTERNAL: {
        "text": "{warning} 内部错误。我已记录到日志。",
        "emoji": {"warning": "warning"},
    },
})
