from app.texts.keys import TextKey


TEXTS_RU = {
    TextKey.START: {
        "text": (
            "{heart} Привет! Я TopSaver.\n\n"
            "Я помогу скачивать видео, фото и музыку из TikTok, YouTube, Instagram Reels и Pinterest.\n\n"
            "Выбери язык интерфейса:"
        ),
        "emoji": {"heart": "heart"},
    },

    TextKey.LANGUAGE_CHOOSE: {
        "text": (
            "{globe} Выбери язык интерфейса.\n\n"
            "Его можно поменять в любой момент через /start."
        ),
        "emoji": {"globe": "telegram"},
    },

    TextKey.LANGUAGE_SAVED: {
        "text": (
            "{check} Язык сохранён: {language_title}\n\n"
            "Теперь пришли ссылку на видео, фото или музыку."
        ),
        "emoji": {"check": "check"},
    },

    TextKey.LANGUAGE_REQUIRED: {
        "text": (
            "{warning} Перед использованием выбери язык интерфейса.\n\n"
            "После этого я смогу правильно показывать меню, качество и озвучки."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.MY_ID: {
        "text": "{info} Твой Telegram ID:\n`{user_id}`",
        "emoji": {"info": "info"},
        "code": ["user_id"],
    },

    TextKey.LINK_NO_URL: {
        "text": (
            "{warning} Я не нашёл ссылку в сообщении.\n\n"
            "Пришли ссылку на YouTube, TikTok, Instagram или Pinterest."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.LINK_UNSUPPORTED: {
        "text": (
            "{warning} Пока я не работаю с этой платформой.\n\n"
            "Сейчас поддерживаем:\n"
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
            "{download} Ссылку принял.\n\n"
            "Платформа: {platform_title}\n"
            "Ссылка: `{url}`\n\n"
            "{hourglass} Дальше подключим metadata, выбор качества, озвучки, кэш и скачивание."
        ),
        "emoji": {
            "download": "download",
            "hourglass": "hourglass",
        },
        "code": ["url"],
    },

    TextKey.ERROR_NO_TOKEN: {
        "text": "{error} BOT_TOKEN не найден.\n\nДобавь BOT_TOKEN в nano.env.",
        "emoji": {"error": "error"},
    },
        TextKey.LINK_ANALYZING: {
        "text": "{hourglass} Анализирую ссылку и получаю информацию о медиа...",
        "emoji": {"hourglass": "hourglass"},
    },

    TextKey.LINK_METADATA_FAILED: {
        "text": (
            "{warning} Не удалось прочитать ссылку.\n\n"
            "Возможно, медиа приватное, удалено или платформа временно ограничила доступ."
        ),
        "emoji": {"warning": "warning"},
    },

        TextKey.ROUTE_DETECTED: {
        "text": (
            "{check} Ссылка распознана.\n\n"
            "Платформа: {platform}\n"
            "Тип: {content_type}\n"
            "Действие: {action}\n"
            "Название: `{title}`\n"
            "Длительность: {duration}\n"
            "Фото: {photo_count}\n"
            "Видео: {video_count}\n"
            "Аудио: {audio_count}\n"
            "Элементов entries: {entries_count}\n"
            "Metadata: {metadata_status}\n"
            "Причина URL: {url_reason}\n"
            "Источник media: {media_detected_from}\n\n"
            "{hourglass} Следующий шаг - подключаем скачивание."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_CHOOSE_QUALITY: {
        "text": (
            "{youtube} YouTube видео найдено.\n\n"
            "Название: `{title}`\n"
            "Длительность: {duration}\n\n"
            "Выбери качество:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_QUALITY_SELECTED: {
        "text": (
            "{check} Качество выбрано: {quality_label}\n\n"
            "{hourglass} Следующий шаг - выбор озвучки и скачивание."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },
      TextKey.YOUTUBE_CHOOSE_AUDIO: {
        "text": (
            "{youtube} Качество выбрано: {quality_label}\n\n"
            "Название: `{title}`\n\n"
            "Выбери озвучку:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_AUDIO_SELECTED: {
        "text": (
            "{check} Озвучка выбрана: {audio_label}\n"
            "Качество: {quality_label}\n\n"
            "{hourglass} Следующий шаг - скачивание видео."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Озвучка выбрана автоматически: {audio_label}\n"
            "Качество: {quality_label}\n\n"
            "{hourglass} Следующий шаг - скачивание видео."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

        TextKey.DOWNLOAD_STARTED: {
        "text": "{download} Начинаю скачивание...",
        "emoji": {"download": "download"},
    },

    TextKey.DOWNLOAD_CACHE_HIT: {
        "text": "{check} Нашёл файл в кэше. Отправляю без повторного скачивания.",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_SUCCESS: {
        "text": "{check} Готово. Файлов отправлено: {items_sent}/{items_total}",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_FAILED: {
        "text": (
            "{warning} Не удалось скачать или отправить медиа.\n\n"
            "Причина: {error_text}"
        ),
        "emoji": {"warning": "warning"},
    },
        TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO: {
        "text": (
            "{youtube} YouTube Shorts найден.\n\n"
            "Название: `{title}`\n"
            "Длительность: {duration}\n\n"
            "Выбери озвучку:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED: {
        "text": (
            "{check} Озвучка для Shorts выбрана: {audio_label}\n\n"
            "{hourglass} Начинаю скачивание в максимальном качестве."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Shorts будет скачан в оригинальной озвучке.\n\n"
            "{hourglass} Начинаю скачивание в максимальном качестве."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },
}

TEXTS_RU.update({
    TextKey.ADD_TO_GROUP: {
        "text": "{telegram} Теперь этого бота можно добавить в группу и пользоваться им.",
        "emoji": {"telegram": "telegram"},
    },
    TextKey.ADD_TO_GROUP_BUTTON: {
        "text": "Добавить бота в группу",
    },
    TextKey.GROUP_WELCOME: {
        "text": "Готов работать в беседе.\n\nОтправь /download ссылка, /dl ссылка{mention_hint}. Ещё можно ответить ссылкой на моё сообщение.",
    },
    TextKey.HELP_PROMPT: {
        "text": "{warning} Опишите проблему одним сообщением. Я отправлю её админу.",
        "emoji": {"warning": "warning"},
    },
    TextKey.HELP_SENT: {
        "text": "{check} Спасибо, я передал проблему админу.",
        "emoji": {"check": "check"},
    },
    TextKey.ACCESS_BANNED: {
        "text": "{stop} Доступ к боту ограничен.",
        "emoji": {"stop": "stop"},
    },
    TextKey.ACCESS_UNAVAILABLE: {
        "text": "{warning} Сейчас бот недоступен.",
        "emoji": {"warning": "warning"},
    },
    TextKey.ACCESS_DAILY_LIMIT: {
        "text": "{stop} Лимит на сегодня исчерпан: {daily_limit} скачиваний в день.\nПопробуй снова завтра.",
        "emoji": {"stop": "stop"},
    },
    TextKey.DOWNLOAD_PROCESSING_MEDIA: {
        "text": "{hourglass} Скачиваю медиа...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE: {
        "text": "{hourglass} Обрабатываю YouTube-видео...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE_MUSIC: {
        "text": "{music} Скачиваю YouTube Music...",
        "emoji": {"music": "music"},
    },
    TextKey.DOWNLOAD_PLATFORM_LIMITED: {
        "text": "{warning} {platform_title} временно ограничила доступ. Это временная проблема, не переживай, скоро поправим.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_NETWORK: {
        "text": "{warning} Не получилось стабильно соединиться с платформой. Попробуй ещё раз чуть позже.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_UNAVAILABLE: {
        "text": "{warning} Не удалось получить это медиа. Возможно, оно приватное, удалено или недоступно.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_GENERIC: {
        "text": "{warning} Не удалось скачать медиа. Попробуй другую ссылку или повтори позже.",
        "emoji": {"warning": "warning"},
    },
    TextKey.REQUIRED_SUBSCRIPTIONS_TEXT: {
        "text": "Чтобы пользоваться ботом, подпишись на обязательные ресурсы ниже.\n\nПосле подписки нажми кнопку проверки.",
    },
    TextKey.REQUIRED_DONE: {
        "text": "{check} Готово. Теперь можно отправлять ссылки.",
        "emoji": {"check": "check"},
    },
    TextKey.REQUIRED_OPEN_PROMPT: {
        "text": "Открой ресурс по кнопке ниже, потом вернись и нажми проверку подписки.",
    },
    TextKey.REQUIRED_RESOURCE_NOT_FOUND: {
        "text": "Ресурс не найден.",
    },
    TextKey.REQUIRED_URL_UNAVAILABLE: {
        "text": "Ссылка недоступна.",
    },
    TextKey.REQUIRED_URL_SENT: {
        "text": "Ссылка отправлена.",
    },
    TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND: {
        "text": "Подписка пока не найдена.",
    },
    TextKey.CALLBACK_INVALID_CHOICE: {
        "text": "Неверный выбор.",
    },
    TextKey.CALLBACK_CHOICE_EXPIRED: {
        "text": "Выбор устарел. Отправь ссылку ещё раз.",
    },
    TextKey.CALLBACK_NOT_FOR_YOU: {
        "text": "Эта кнопка не для тебя.",
    },
    TextKey.YOUTUBE_AUDIO_MISSING: {
        "text": "Такой озвучки нет у этого видео. Выбери Original или другой язык.",
    },
    TextKey.ERROR_INTERNAL: {
        "text": "{warning} Внутренняя ошибка. Я уже записал её в лог.",
        "emoji": {"warning": "warning"},
    },
})
