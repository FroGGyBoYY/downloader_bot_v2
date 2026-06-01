from app.texts.keys import TextKey


TEXTS_AR = {
    TextKey.START: {
        "text": (
            "{heart} مرحباً! أنا TopSaver.\n\n"
            "أساعدك على تحميل الفيديوهات والصور والموسيقى من TikTok و YouTube و Instagram Reels و Pinterest.\n\n"
            "اختر لغة الواجهة:"
        ),
        "emoji": {"heart": "heart"},
    },

    TextKey.LANGUAGE_CHOOSE: {
        "text": "{globe} اختر لغة الواجهة.\n\nيمكنك تغييرها في أي وقت عبر /start.",
        "emoji": {"globe": "telegram"},
    },

    TextKey.LANGUAGE_SAVED: {
        "text": "{check} تم حفظ اللغة: {language_title}\n\nأرسل الآن رابط فيديو أو صورة أو موسيقى.",
        "emoji": {"check": "check"},
    },

    TextKey.LANGUAGE_REQUIRED: {
        "text": (
            "{warning} قبل استخدام البوت، اختر لغة الواجهة.\n\n"
            "بعد ذلك سأتمكن من عرض القوائم والجودة والمسارات الصوتية بشكل صحيح."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.MY_ID: {
        "text": "{info} Telegram ID الخاص بك:\n`{user_id}`",
        "emoji": {"info": "info"},
        "code": ["user_id"],
    },

    TextKey.LINK_NO_URL: {
        "text": "{warning} لم أجد رابطاً في رسالتك.\n\nأرسل رابط YouTube أو TikTok أو Instagram أو Pinterest.",
        "emoji": {"warning": "warning"},
    },

    TextKey.LINK_UNSUPPORTED: {
        "text": (
            "{warning} هذه المنصة غير مدعومة حالياً.\n\n"
            "المنصات المدعومة الآن:\n"
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
            "{download} تم استلام الرابط.\n\n"
            "المنصة: {platform_title}\n"
            "الرابط: `{url}`\n\n"
            "{hourglass} بعد ذلك سنضيف metadata واختيار الجودة والمسارات الصوتية والكاش والتحميل."
        ),
        "emoji": {
            "download": "download",
            "hourglass": "hourglass",
        },
        "code": ["url"],
    },

        TextKey.LINK_ANALYZING: {
        "text": "{hourglass} جارٍ تحليل الرابط وقراءة معلومات الوسائط...",
        "emoji": {"hourglass": "hourglass"},
    },

    TextKey.LINK_METADATA_FAILED: {
        "text": (
            "{warning} تعذر قراءة هذا الرابط.\n\n"
            "قد يكون المحتوى خاصاً أو محذوفاً، أو أن المنصة قيّدت الوصول مؤقتاً."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ROUTE_DETECTED: {
        "text": (
            "{check} تم التعرف على الرابط.\n\n"
            "المنصة: {platform}\n"
            "النوع: {content_type}\n"
            "الإجراء: {action}\n"
            "العنوان: `{title}`\n"
            "المدة: {duration}\n"
            "عدد العناصر: {entries_count}\n\n"
            "{hourglass} الخطوة التالية: التحميل."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_CHOOSE_QUALITY: {
        "text": (
            "{youtube} تم العثور على فيديو YouTube.\n\n"
            "العنوان: `{title}`\n"
            "المدة: {duration}\n\n"
            "اختر الجودة:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_QUALITY_SELECTED: {
        "text": (
            "{check} تم اختيار الجودة: {quality_label}\n\n"
            "{hourglass} الخطوة التالية: اختيار المسار الصوتي والتحميل."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

     TextKey.YOUTUBE_CHOOSE_AUDIO: {
        "text": (
            "{youtube} تم اختيار الجودة: {quality_label}\n\n"
            "العنوان: `{title}`\n\n"
            "اختر المسار الصوتي:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_AUDIO_SELECTED: {
        "text": (
            "{check} تم اختيار الصوت: {audio_label}\n"
            "الجودة: {quality_label}\n\n"
            "{hourglass} الخطوة التالية: تحميل الفيديو."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} تم اختيار الصوت تلقائياً: {audio_label}\n"
            "الجودة: {quality_label}\n\n"
            "{hourglass} الخطوة التالية: تحميل الفيديو."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.DOWNLOAD_STARTED: {
        "text": "{download} جارٍ بدء التحميل...",
        "emoji": {"download": "download"},
    },

    TextKey.DOWNLOAD_CACHE_HIT: {
        "text": "{check} وجدت الملف في الكاش. سأرسله بدون تحميله مرة أخرى.",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_SUCCESS: {
        "text": "{check} تم. الملفات المرسلة: {items_sent}/{items_total}",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_FAILED: {
        "text": (
            "{warning} تعذر تحميل أو إرسال هذا المحتوى.\n\n"
            "السبب: {error_text}"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ERROR_NO_TOKEN: {
        "text": "{error} لم يتم العثور على BOT_TOKEN.\n\nأضف BOT_TOKEN إلى nano.env.",
        "emoji": {"error": "error"},
    },

    TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO: {
        "text": (
            "{youtube} تم العثور على YouTube Shorts.\n\n"
            "العنوان: `{title}`\n"
            "المدة: {duration}\n\n"
            "اختر المسار الصوتي:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED: {
        "text": (
            "{check} تم اختيار صوت Shorts: {audio_label}\n\n"
            "{hourglass} جارٍ بدء التحميل بأعلى جودة."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} سيتم تحميل Shorts بالصوت الأصلي.\n\n"
            "{hourglass} جارٍ بدء التحميل بأعلى جودة."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },
}

TEXTS_AR.update({
    TextKey.ADD_TO_GROUP: {
        "text": "{telegram} يمكنك الآن إضافة هذا البوت إلى مجموعة واستخدامه هناك.",
        "emoji": {"telegram": "telegram"},
    },
    TextKey.ADD_TO_GROUP_BUTTON: {
        "text": "إضافة البوت إلى مجموعة",
    },
    TextKey.GROUP_WELCOME: {
        "text": "أنا جاهز للعمل في هذه المجموعة.\n\nأرسل /download رابط أو /dl رابط{mention_hint}. يمكنك أيضًا الرد على رسالتي برابط.",
    },
    TextKey.HELP_PROMPT: {
        "text": "{warning} اشرح المشكلة في رسالة واحدة. سأرسلها إلى المسؤول.",
        "emoji": {"warning": "warning"},
    },
    TextKey.HELP_SENT: {
        "text": "{check} شكرًا، أرسلت المشكلة إلى المسؤول.",
        "emoji": {"check": "check"},
    },
    TextKey.ACCESS_BANNED: {
        "text": "{stop} الوصول إلى البوت مقيّد.",
        "emoji": {"stop": "stop"},
    },
    TextKey.ACCESS_UNAVAILABLE: {
        "text": "{warning} البوت غير متاح حاليًا.",
        "emoji": {"warning": "warning"},
    },
    TextKey.ACCESS_DAILY_LIMIT: {
        "text": "{stop} وصلت إلى حد اليوم: {daily_limit} تنزيلات في اليوم.\nحاول مرة أخرى غدًا.",
        "emoji": {"stop": "stop"},
    },
    TextKey.DOWNLOAD_PROCESSING_MEDIA: {
        "text": "{hourglass} جارٍ تنزيل الوسائط...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE: {
        "text": "{hourglass} جارٍ معالجة فيديو YouTube...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE_MUSIC: {
        "text": "{music} جارٍ تنزيل YouTube Music...",
        "emoji": {"music": "music"},
    },
    TextKey.DOWNLOAD_PLATFORM_LIMITED: {
        "text": "{warning} قام {platform_title} بتقييد الوصول مؤقتًا. هذه مشكلة مؤقتة، لا تقلق، سنصلحها قريبًا.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_NETWORK: {
        "text": "{warning} تعذر الاتصال بالمنصة بشكل مستقر. حاول لاحقًا.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_UNAVAILABLE: {
        "text": "{warning} تعذر الوصول إلى هذه الوسائط. قد تكون خاصة أو محذوفة أو غير متاحة.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_GENERIC: {
        "text": "{warning} تعذر تنزيل الوسائط. جرّب رابطًا آخر أو حاول لاحقًا.",
        "emoji": {"warning": "warning"},
    },
    TextKey.REQUIRED_SUBSCRIPTIONS_TEXT: {
        "text": "لاستخدام البوت، اشترك في الموارد المطلوبة أدناه.\n\nبعد الاشتراك اضغط زر التحقق.",
    },
    TextKey.REQUIRED_DONE: {
        "text": "{check} تم. يمكنك الآن إرسال الروابط.",
        "emoji": {"check": "check"},
    },
    TextKey.REQUIRED_OPEN_PROMPT: {
        "text": "افتح المورد من الزر أدناه، ثم ارجع واضغط زر التحقق من الاشتراك.",
    },
    TextKey.REQUIRED_RESOURCE_NOT_FOUND: {
        "text": "لم يتم العثور على المورد.",
    },
    TextKey.REQUIRED_URL_UNAVAILABLE: {
        "text": "الرابط غير متاح.",
    },
    TextKey.REQUIRED_URL_SENT: {
        "text": "تم إرسال الرابط.",
    },
    TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND: {
        "text": "لم يتم العثور على الاشتراك بعد.",
    },
    TextKey.CALLBACK_INVALID_CHOICE: {
        "text": "اختيار غير صالح.",
    },
    TextKey.CALLBACK_CHOICE_EXPIRED: {
        "text": "انتهت صلاحية الاختيار. أرسل الرابط مرة أخرى.",
    },
    TextKey.CALLBACK_NOT_FOR_YOU: {
        "text": "هذا الزر ليس لك.",
    },
    TextKey.YOUTUBE_AUDIO_MISSING: {
        "text": "هذا المسار الصوتي غير متاح لهذا الفيديو. اختر Original أو لغة أخرى.",
    },
    TextKey.ERROR_INTERNAL: {
        "text": "{warning} خطأ داخلي. تم حفظه في السجل.",
        "emoji": {"warning": "warning"},
    },
})
