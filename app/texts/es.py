from app.texts.keys import TextKey


TEXTS_ES = {
    TextKey.START: {
        "text": (
            "{heart} ¡Hola! Soy TopSaver.\n\n"
            "Puedo ayudarte a descargar videos, fotos y música de TikTok, YouTube, Instagram Reels y Pinterest.\n\n"
            "Elige el idioma de la interfaz:"
        ),
        "emoji": {"heart": "heart"},
    },

    TextKey.LANGUAGE_CHOOSE: {
        "text": "{globe} Elige el idioma de la interfaz.\n\nPuedes cambiarlo en cualquier momento con /start.",
        "emoji": {"globe": "telegram"},
    },

    TextKey.LANGUAGE_SAVED: {
        "text": "{check} Idioma guardado: {language_title}\n\nAhora envíame un enlace a un video, foto o música.",
        "emoji": {"check": "check"},
    },

    TextKey.LANGUAGE_REQUIRED: {
        "text": (
            "{warning} Antes de usar el bot, elige el idioma de la interfaz.\n\n"
            "Después podré mostrar menús, calidad y pistas de audio correctamente."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.MY_ID: {
        "text": "{info} Tu Telegram ID:\n`{user_id}`",
        "emoji": {"info": "info"},
        "code": ["user_id"],
    },

    TextKey.LINK_NO_URL: {
        "text": "{warning} No encontré ningún enlace en tu mensaje.\n\nEnvía un enlace de YouTube, TikTok, Instagram o Pinterest.",
        "emoji": {"warning": "warning"},
    },

    TextKey.LINK_UNSUPPORTED: {
        "text": (
            "{warning} Esta plataforma aún no está disponible.\n\n"
            "Ahora soportamos:\n"
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
            "{download} Enlace aceptado.\n\n"
            "Plataforma: {platform_title}\n"
            "URL: `{url}`\n\n"
            "{hourglass} Luego añadiremos metadata, calidad, pistas de audio, caché y descarga."
        ),
        "emoji": {
            "download": "download",
            "hourglass": "hourglass",
        },
        "code": ["url"],
    },

    TextKey.LINK_ANALYZING: {
        "text": "{hourglass} Analizando el enlace y leyendo la información del medio...",
        "emoji": {"hourglass": "hourglass"},
    },

    TextKey.LINK_METADATA_FAILED: {
        "text": (
            "{warning} No pude leer este enlace.\n\n"
            "Es posible que el contenido sea privado, haya sido eliminado o que la plataforma haya limitado temporalmente el acceso."
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ROUTE_DETECTED: {
        "text": (
            "{check} Enlace reconocido.\n\n"
            "Plataforma: {platform}\n"
            "Tipo: {content_type}\n"
            "Acción: {action}\n"
            "Título: `{title}`\n"
            "Duración: {duration}\n"
            "Elementos: {entries_count}\n\n"
            "{hourglass} Siguiente paso: descarga."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_CHOOSE_QUALITY: {
        "text": (
            "{youtube} Video de YouTube encontrado.\n\n"
            "Título: `{title}`\n"
            "Duración: {duration}\n\n"
            "Elige la calidad:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_QUALITY_SELECTED: {
        "text": (
            "{check} Calidad seleccionada: {quality_label}\n\n"
            "{hourglass} Siguiente paso: selección de pista de audio y descarga."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

     TextKey.YOUTUBE_CHOOSE_AUDIO: {
        "text": (
            "{youtube} Calidad seleccionada: {quality_label}\n\n"
            "Título: `{title}`\n\n"
            "Elige la pista de audio:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_AUDIO_SELECTED: {
        "text": (
            "{check} Audio seleccionado: {audio_label}\n"
            "Calidad: {quality_label}\n\n"
            "{hourglass} Siguiente paso: descargar el video."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Audio seleccionado automáticamente: {audio_label}\n"
            "Calidad: {quality_label}\n\n"
            "{hourglass} Siguiente paso: descargar el video."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.DOWNLOAD_STARTED: {
        "text": "{download} Empezando la descarga...",
        "emoji": {"download": "download"},
    },

    TextKey.DOWNLOAD_CACHE_HIT: {
        "text": "{check} Encontré el archivo en caché. Lo envío sin descargarlo otra vez.",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_SUCCESS: {
        "text": "{check} Listo. Archivos enviados: {items_sent}/{items_total}",
        "emoji": {"check": "check"},
    },

    TextKey.DOWNLOAD_FAILED: {
        "text": (
            "{warning} No pude descargar o enviar este medio.\n\n"
            "Motivo: {error_text}"
        ),
        "emoji": {"warning": "warning"},
    },

    TextKey.ERROR_NO_TOKEN: {
        "text": "{error} No se encontró BOT_TOKEN.\n\nAñade BOT_TOKEN a nano.env.",
        "emoji": {"error": "error"},
    },

    TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO: {
        "text": (
            "{youtube} YouTube Shorts encontrado.\n\n"
            "Título: `{title}`\n"
            "Duración: {duration}\n\n"
            "Elige la pista de audio:"
        ),
        "emoji": {"youtube": "youtube"},
        "code": ["title"],
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED: {
        "text": (
            "{check} Audio para Shorts seleccionado: {audio_label}\n\n"
            "{hourglass} Empezando la descarga en calidad máxima."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },

    TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED: {
        "text": (
            "{check} Shorts se descargará con el audio original.\n\n"
            "{hourglass} Empezando la descarga en calidad máxima."
        ),
        "emoji": {"check": "check", "hourglass": "hourglass"},
    },
}

TEXTS_ES.update({
    TextKey.ADD_TO_GROUP: {
        "text": "{telegram} Ahora puedes añadir este bot a un grupo y usarlo allí.",
        "emoji": {"telegram": "telegram"},
    },
    TextKey.ADD_TO_GROUP_BUTTON: {
        "text": "Añadir bot al grupo",
    },
    TextKey.GROUP_WELCOME: {
        "text": "Listo para trabajar en este grupo.\n\nEnvía /download enlace, /dl enlace{mention_hint}. También puedes responder con un enlace a mi mensaje.",
    },
    TextKey.HELP_PROMPT: {
        "text": "{warning} Describe el problema en un solo mensaje. Se lo enviaré al admin.",
        "emoji": {"warning": "warning"},
    },
    TextKey.HELP_SENT: {
        "text": "{check} Gracias, envié el problema al admin.",
        "emoji": {"check": "check"},
    },
    TextKey.ACCESS_BANNED: {
        "text": "{stop} El acceso al bot está restringido.",
        "emoji": {"stop": "stop"},
    },
    TextKey.ACCESS_UNAVAILABLE: {
        "text": "{warning} El bot no está disponible ahora.",
        "emoji": {"warning": "warning"},
    },
    TextKey.ACCESS_DAILY_LIMIT: {
        "text": "{stop} Has alcanzado el límite de hoy: {daily_limit} descargas por día.\nInténtalo de nuevo mañana.",
        "emoji": {"stop": "stop"},
    },
    TextKey.DOWNLOAD_PROCESSING_MEDIA: {
        "text": "{hourglass} Descargando media...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE: {
        "text": "{hourglass} Procesando video de YouTube...",
        "emoji": {"hourglass": "hourglass"},
    },
    TextKey.DOWNLOAD_PROCESSING_YOUTUBE_MUSIC: {
        "text": "{music} Descargando YouTube Music...",
        "emoji": {"music": "music"},
    },
    TextKey.DOWNLOAD_PLATFORM_LIMITED: {
        "text": "{warning} {platform_title} limitó temporalmente el acceso. Es temporal, no te preocupes, lo arreglaremos pronto.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_NETWORK: {
        "text": "{warning} No pude conectar de forma estable con la plataforma. Inténtalo un poco más tarde.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_UNAVAILABLE: {
        "text": "{warning} No pude acceder a este media. Puede ser privado, eliminado o no disponible.",
        "emoji": {"warning": "warning"},
    },
    TextKey.DOWNLOAD_ERROR_GENERIC: {
        "text": "{warning} No pude descargar el media. Prueba otro enlace o inténtalo más tarde.",
        "emoji": {"warning": "warning"},
    },
    TextKey.REQUIRED_SUBSCRIPTIONS_TEXT: {
        "text": "Para usar el bot, suscríbete a los recursos obligatorios de abajo.\n\nDespués pulsa el botón de verificación.",
    },
    TextKey.REQUIRED_DONE: {
        "text": "{check} Listo. Ahora puedes enviar enlaces.",
        "emoji": {"check": "check"},
    },
    TextKey.REQUIRED_OPEN_PROMPT: {
        "text": "Abre el recurso con el botón de abajo, vuelve y pulsa verificar suscripción.",
    },
    TextKey.REQUIRED_RESOURCE_NOT_FOUND: {
        "text": "Recurso no encontrado.",
    },
    TextKey.REQUIRED_URL_UNAVAILABLE: {
        "text": "El enlace no está disponible.",
    },
    TextKey.REQUIRED_URL_SENT: {
        "text": "Enlace enviado.",
    },
    TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND: {
        "text": "Aún no se encontró la suscripción.",
    },
    TextKey.CALLBACK_INVALID_CHOICE: {
        "text": "Elección no válida.",
    },
    TextKey.CALLBACK_CHOICE_EXPIRED: {
        "text": "La elección expiró. Envía el enlace otra vez.",
    },
    TextKey.CALLBACK_NOT_FOR_YOU: {
        "text": "Este botón no es para ti.",
    },
    TextKey.YOUTUBE_AUDIO_MISSING: {
        "text": "Esta pista de audio no está disponible para este video. Elige Original u otro idioma.",
    },
    TextKey.ERROR_INTERNAL: {
        "text": "{warning} Error interno. Ya lo guardé en el log.",
        "emoji": {"warning": "warning"},
    },
})
