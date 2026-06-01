from app.texts.keys import TextKey


TEXTS_TH = {
    TextKey.START: {
        "text": (
            "{heart} สวัสดี! ฉันคือ TopSaver\n\n"
            "ฉันช่วยดาวน์โหลดวิดีโอ รูปภาพ และเพลงจาก TikTok, YouTube, Instagram Reels และ Pinterest ได้\n\n"
            "เลือกภาษาของอินเทอร์เฟซ:"
        ),
        "emoji": {"heart": "heart"},
    },

    TextKey.LANGUAGE_CHOOSE: {
        "text": "{globe} เลือกภาษาของอินเทอร์เฟซ\n\nคุณสามารถเปลี่ยนได้ตลอดเวลาด้วย /start",
        "emoji": {"globe": "telegram"},
    },

    TextKey.LANGUAGE_SAVED: {
        "text": "{check} บันทึกภาษาแล้ว: {language_title}\n\nตอนนี้ส่งลิงก์วิดีโอ รูปภาพ หรือเพลงมาได้เลย",
        "emoji": {"check": "check"},
    },

    TextKey.LANGUAGE_REQUIRED: {
        "text": (
            "{warning} ก่อนใช้งานบอท กรุณาเลือกภาษาของอินเทอร์เฟซก่อน\n\n"
            "หลังจากนั้นฉันจะแสดงเมนู คุณภาพวิดีโอ และแทร็กเสียงได้อย่างถูกต้อง"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.MY_ID: {
        "text": "{info} Telegram ID ของคุณ:\n`{user_id}`",
        "emoji": {"info": "info"},
        "code": ["user_id"],
    },

    TextKey.LINK_NO_URL: {
        "text": "{warning} ฉันไม่พบลิงก์ในข้อความของคุณ\n\nส่งลิงก์ YouTube, TikTok, Instagram หรือ Pinterest มาได้เลย",
        "emoji": {"warning": "warning"},
    },

    TextKey.LINK_UNSUPPORTED: {
        "text": (
            "{warning} ตอนนี้ยังไม่รองรับแพลตฟอร์มนี้\n\n"
            "ตอนนี้รองรับ:\n"
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
            "{download} รับลิงก์แล้ว\n\n"
            "แพลตฟอร์ม: {platform_title}\n"
            "ลิงก์: `{url}`\n\n"
            "{hourglass} ขั้นต่อไปเราจะเพิ่ม metadata การเลือกคุณภาพ แทร็กเสียง แคช และการดาวน์โหลด"
        ),
        "emoji": {
            "download": "download",
            "hourglass": "hourglass",
        },
        "code": ["url"],
    },

        TextKey.LINK_ANALYZING: {
        "text": "{hourglass} กำลังวิเคราะห์ลิงก์และอ่านข้อมูลสื่อ...",
        "emoji": {"hourglass": "hourglass"},
    },

    TextKey.LINK_METADATA_FAILED: {
        "text": (
            "{warning} ไม่สามารถอ่านลิงก์นี้ได้\n\n"
            "สื่อนี้อาจเป็นส่วนตัว ถูกลบแล้ว หรือแพลตฟอร์มจำกัดการเข้าถึงชั่วคราว"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ROUTE_DETECTED: {
        "text": (
            "{check} ตรวจพบลิงก์แล้ว\n\n"
            "แพลตฟอร์ม: {platform}\n"
            "ประเภท: {content_type}\n"
            "การทำงาน: {action}\n"
            "ชื่อ: `{title}`\n"
            "ความยาว: {duration}\n"
            "จำนวนรายการ: {entries_count}\n\n"
            "{hourglass} ขั้นตอนต่อไป: ดาวน์โหลด"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_CHOOSE_QUALITY: {
        "text": (
            "{youtube} พบวิดีโอ YouTube แล้ว\n\n"
            "ชื่อ: `{title}`\n"
            "ความยาว: {duration}\n\n"
            "เลือกคุณภาพ:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_QUALITY_SELECTED: {
        "text": (
            "{check} เลือกคุณภาพแล้ว: {quality_label}\n\n"
            "{hourglass} ขั้นตอนต่อไป: เลือกแทร็กเสียงและดาวน์โหลด"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

  TextKey.YOUTUBE_CHOOSE_AUDIO: {
        "text": (
            "{youtube} เลือกคุณภาพแล้ว: {quality_label}\n\n"
            "ชื่อ: `{title}`\n\n"
            "เลือกแทร็กเสียง:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_AUDIO_SELECTED: {
        "text": (
            "{check} เลือกเสียงแล้ว: {audio_label}\n"
            "คุณภาพ: {quality_label}\n\n"
            "{hourglass} ขั้นตอนต่อไป: ดาวน์โหลดวิดีโอ"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} เลือกเสียงอัตโนมัติแล้ว: {audio_label}\n"
            "คุณภาพ: {quality_label}\n\n"
            "{hourglass} ขั้นตอนต่อไป: ดาวน์โหลดวิดีโอ"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.DOWNLOAD_STARTED: {
        "text": "{download} กำลังเริ่มดาวน์โหลด...",
        "emoji": {"download": "download"},
    },

    TextKey.DOWNLOAD_CACHE_HIT: {
        "text": "{check} พบไฟล์ในแคชแล้ว กำลังส่งโดยไม่ดาวน์โหลดซ้ำ",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_SUCCESS: {
        "text": "{check} เสร็จแล้ว ส่งไฟล์แล้ว: {items_sent}/{items_total}",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_FAILED: {
        "text": (
            "{warning} ไม่สามารถดาวน์โหลดหรือส่งสื่อนี้ได้\n\n"
            "สาเหตุ: {error_text}"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ERROR_NO_TOKEN: {
        "text": "{error} ไม่พบ BOT_TOKEN\n\nเพิ่ม BOT_TOKEN ใน nano.env",
        "emoji": {"error": "error"},
    },

    TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO: {
        "text": (
            "{youtube} พบ YouTube Shorts แล้ว\n\n"
            "ชื่อ: `{title}`\n"
            "ความยาว: {duration}\n\n"
            "เลือกแทร็กเสียง:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED: {
        "text": (
            "{check} เลือกเสียงสำหรับ Shorts แล้ว: {audio_label}\n\n"
            "{hourglass} กำลังเริ่มดาวน์โหลดด้วยคุณภาพสูงสุด"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Shorts จะถูกดาวน์โหลดด้วยเสียงต้นฉบับ\n\n"
            "{hourglass} กำลังเริ่มดาวน์โหลดด้วยคุณภาพสูงสุด"
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

}

TEXTS_TH.update({
    TextKey.ADD_TO_GROUP: {
        "text": "{telegram} ตอนนี้คุณสามารถเพิ่มบอตนี้เข้าไปในกลุ่มและใช้งานได้แล้ว",
        "emoji": {"telegram": "telegram"},
    },
    TextKey.ADD_TO_GROUP_BUTTON: {
        "text": "เพิ่มบอตเข้ากลุ่ม",
    },
    TextKey.GROUP_WELCOME: {
        "text": "พร้อมทำงานในกลุ่มนี้แล้ว\n\nส่ง /download ลิงก์, /dl ลิงก์{mention_hint} หรือจะตอบกลับข้อความของฉันพร้อมลิงก์ก็ได้",
    },
    TextKey.HELP_PROMPT: {
        "text": "{warning} อธิบายปัญหาในข้อความเดียว แล้วฉันจะส่งให้แอดมิน",
        "emoji": {"warning": "warning"},
    },
    TextKey.HELP_SENT: {
        "text": "{check} ขอบคุณ ฉันส่งปัญหาให้แอดมินแล้ว",
        "emoji": {"check": "check"},
    },
    TextKey.ACCESS_BANNED: {
        "text": "{stop} การเข้าถึงบอตถูกจำกัด",
        "emoji": {"stop": "stop"},
    },
    TextKey.ACCESS_UNAVAILABLE: {
        "text": "{warning} ขณะนี้บอตไม่พร้อมใช้งาน",
        "emoji": {"warning": "warning"},
    },
    TextKey.ACCESS_DAILY_LIMIT: {
        "text": "{stop} ใช้โควตาวันนี้ครบแล้ว: {daily_limit} ดาวน์โหลดต่อวัน\nลองอีกครั้งพรุ่งนี้",
        "emoji": {"stop": "stop"},
    },
    TextKey.DOWNLOAD_PROCESSING_MEDIA: {
        "text": "{hourglass} กำลังดาวน์โหลดสื่อ...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE: {
        "text": "{hourglass} กำลังประมวลผลวิดีโอ YouTube...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE_MUSIC: {
        "text": "{music} กำลังดาวน์โหลด YouTube Music...",
        "emoji": {"music": "music"},
    },
    TextKey.DOWNLOAD_PLATFORM_LIMITED: {
        "text": "{warning} {platform_title} จำกัดการเข้าถึงชั่วคราว ไม่ต้องกังวล เราจะรีบแก้ไข",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_NETWORK: {
        "text": "{warning} เชื่อมต่อกับแพลตฟอร์มได้ไม่เสถียร ลองใหม่อีกครั้งในภายหลัง",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_UNAVAILABLE: {
        "text": "{warning} ไม่สามารถเข้าถึงสื่อนี้ได้ อาจเป็นส่วนตัว ถูกลบ หรือไม่พร้อมใช้งาน",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_GENERIC: {
        "text": "{warning} ไม่สามารถดาวน์โหลดสื่อได้ ลองลิงก์อื่นหรือลองใหม่ภายหลัง",
        "emoji": {"warning": "warning"},
    },
    TextKey.REQUIRED_SUBSCRIPTIONS_TEXT: {
        "text": "หากต้องการใช้บอต กรุณาสมัครรับทรัพยากรที่จำเป็นด้านล่าง\n\nหลังจากสมัครแล้วให้กดปุ่มตรวจสอบ",
    },
    TextKey.REQUIRED_DONE: {
        "text": "{check} เรียบร้อย ตอนนี้คุณสามารถส่งลิงก์ได้แล้ว",
        "emoji": {"check": "check"},
    },
    TextKey.REQUIRED_OPEN_PROMPT: {
        "text": "เปิดทรัพยากรด้วยปุ่มด้านล่าง จากนั้นกลับมาแล้วกดตรวจสอบการสมัคร",
    },
    TextKey.REQUIRED_RESOURCE_NOT_FOUND: {
        "text": "ไม่พบทรัพยากร",
    },
    TextKey.REQUIRED_URL_UNAVAILABLE: {
        "text": "ลิงก์ไม่พร้อมใช้งาน",
    },
    TextKey.REQUIRED_URL_SENT: {
        "text": "ส่งลิงก์แล้ว",
    },
    TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND: {
        "text": "ยังไม่พบการสมัคร",
    },
    TextKey.CALLBACK_INVALID_CHOICE: {
        "text": "ตัวเลือกไม่ถูกต้อง",
    },
    TextKey.CALLBACK_CHOICE_EXPIRED: {
        "text": "ตัวเลือกหมดอายุแล้ว ส่งลิงก์อีกครั้ง",
    },
    TextKey.CALLBACK_NOT_FOR_YOU: {
        "text": "ปุ่มนี้ไม่ใช่ของคุณ",
    },
    TextKey.YOUTUBE_AUDIO_MISSING: {
        "text": "วิดีโอนี้ไม่มีเสียงภาษานี้ เลือก Original หรือภาษาอื่น",
    },
    TextKey.ERROR_INTERNAL: {
        "text": "{warning} เกิดข้อผิดพลาดภายใน ฉันบันทึกไว้ใน log แล้ว",
        "emoji": {"warning": "warning"},
    },
})
