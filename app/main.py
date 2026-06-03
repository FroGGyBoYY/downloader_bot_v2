import logging
from datetime import time, timedelta, timezone

from telegram import BotCommand, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from app.config import load_settings
from app.db.database import init_db
from app.handlers.callbacks import (
    language_callback_handler,
    youtube_audio_callback_handler,
    youtube_quality_callback_handler,
    youtube_shorts_audio_callback_handler,
)

from app.handlers.debug import debug_cmd, debug_meta_cmd, ping_cmd
from app.handlers.cookies_admin import (
    admin_cookies_help_cmd,
    cookie_check_cmd,
    cookie_replace_cmd,
)
from app.handlers.admin_cache_import import (
    admin_receive_video_message_handler,
    admin_receive_video_off_cmd,
    admin_receive_video_on_cmd,
)
from app.handlers.admin import (
    ad_overview_cmd,
    admin_add_cmd,
    admin_del_cmd,
    admin_list_cmd,
    admin_panel_cmd,
    admin_run_cmd,
    bot_status_cmd,
    banned_cmd,
    ban_cmd,
    cache_stats_cmd,
    cleanup_temp_cmd,
    cookie_health_cmd,
    daily_report_cmd,
    db_export_cmd,
    db_tables_cmd,
    errors_cmd,
    failed_downloads_cmd,
    groups_cmd,
    health_check_cmd,
    maintenance_off_cmd,
    maintenance_on_cmd,
    maintenance_status_cmd,
    platform_health_cmd,
    platform_stats_cmd,
    recent_downloads_cmd,
    req_overview_cmd,
    reports_cmd,
    table_export_cmd,
    top_downloads_cmd,
    unban_cmd,
    user_cmd,
    users_cmd,
    users_count_cmd,
    users_top_cmd,
)
from app.handlers.ads import (
    ad8_add_cmd,
    ad8_del_cmd,
    ad8_list_cmd,
    ad8_stats_cmd,
    ad8_stats_txt_cmd,
    ad8_status_cmd,
    ad_add_cmd,
    ad_add_reply_text_handler,
    ad_click_callback_handler,
    ad_del_cmd,
    ad_list_cmd,
    ad_stats_cmd,
    ad_stats_txt_cmd,
    ad_status_cmd,
    broadcast_cmd,
    broadcast_users_cmd,
    friend_add_cmd,
    friend_del_cmd,
    friend_list_cmd,
)
from app.handlers.errors import error_handler
from app.handlers.groups import bot_chat_member_handler
from app.handlers.links import link_message_handler
from app.handlers.proxies import (
    PROXY_DELETE_CONFIRM_PREFIX,
    add_proxy_cmd,
    add_proxy_list_cmd,
    delete_all_proxy_cmd,
    delete_one_proxy_cmd,
    proxy_delete_callback_handler,
    proxy_hs_cmd,
    proxy_list_cmd,
    proxy_stats_cmd,
)
from app.handlers.raw_updates import raw_update_logger
from app.handlers.required_subscriptions import (
    req_add_cmd,
    req_checker_cmd,
    req_del_cmd,
    req_edit_cmd,
    req_list_cmd,
    req_list_txt_cmd,
    req_stats_cmd,
    req_status_cmd,
    req_text_cmd,
    required_check_callback_handler,
    required_open_callback_handler,
)
from app.handlers.start import (
    add_to_group_cmd,
    myid_cmd,
    start_cmd,
    welcome_clear_cmd,
    welcome_set_cmd,
    welcome_status_cmd,
)
from app.handlers.user_reports import pending_problem_report_message_handler, report_problem_cmd
from app.logging_config import setup_logging
from app.services.daily_report_service import send_daily_admin_report
from app.services.health_service import send_cookie_health_if_needed
from app.services.ads_service import AD_CLICK_PREFIX, send_scheduled_ads_job
from app.services.required_subscriptions_service import (
    REQUIRED_CHECK_CALLBACK,
    REQUIRED_OPEN_PREFIX,
)
from app.telegram_ui.keyboards import (
    LANGUAGE_CALLBACK_PREFIX,
    YOUTUBE_AUDIO_CALLBACK_PREFIX,
    YOUTUBE_QUALITY_CALLBACK_PREFIX,
    YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX,
)

from app.services.legacy_youtube_service import (
    LEGACY_YOUTUBE_AUDIO_PREFIX,
    LEGACY_YOUTUBE_BACK_PREFIX,
    LEGACY_YOUTUBE_QUALITY_PREFIX,
    legacy_youtube_audio_callback_handler,
    legacy_youtube_back_callback_handler,
    legacy_youtube_quality_callback_handler,
)

logger = logging.getLogger(__name__)


async def post_init(application) -> None:
    settings = application.bot_data["settings"]

    logger.info("POST_INIT started")
    logger.info("ENV file=%s", settings.env_file)
    logger.info("Project base_dir=%s", settings.base_dir)
    logger.info("DB path=%s", settings.db_path)
    logger.info("USE_LOCAL_BOT_API=%s", settings.use_local_bot_api)
    logger.info("BOT_API_BASE_URL=%s", settings.bot_api_base_url)
    
    me = await application.bot.get_me()

    logger.info(
        "Telegram getMe OK | bot_id=%s username=@%s first_name=%s",
        me.id,
        me.username,
        me.first_name,
    )
    application.bot_data["bot_id"] = me.id
    application.bot_data["bot_username"] = me.username

    await application.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
        BotCommand("add_to_group", "Добавить бота в группу"),
        BotCommand("help", "Сообщить о проблеме"),
    ])
    logger.info("Bot command menu updated")

    webhook_info = await application.bot.get_webhook_info()

    logger.info(
        "Webhook info | url=%s pending=%s last_error=%s",
        webhook_info.url or "empty",
        webhook_info.pending_update_count,
        webhook_info.last_error_message or "none",
    )

    # Для polling webhook должен быть пустой.
    if webhook_info.url:
        logger.warning("Webhook URL is not empty. Deleting webhook before polling.")
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.warning("Webhook deleted.")

    if application.job_queue:
        local_tz = timezone(timedelta(hours=settings.local_tz_hours))
        report_hour = max(0, min(23, settings.daily_admin_report_hour))
        cookie_interval = max(1, settings.cookie_health_check_interval_hours) * 60 * 60
        scheduled_ad_interval = max(1, settings.scheduled_ad_interval_hours) * 60 * 60

        application.job_queue.run_daily(
            send_daily_admin_report,
            time=time(hour=report_hour, minute=0, tzinfo=local_tz),
            name="daily_admin_report",
        )
        application.job_queue.run_repeating(
            send_cookie_health_if_needed,
            interval=cookie_interval,
            first=300,
            name="cookie_health_check",
        )
        application.job_queue.run_repeating(
            send_scheduled_ads_job,
            interval=scheduled_ad_interval,
            first=600,
            name="scheduled_ads",
        )

        logger.info(
            "Admin jobs scheduled | daily_report_hour=%s local_tz=%s cookie_interval_hours=%s scheduled_ad_interval_hours=%s",
            report_hour,
            settings.local_tz_hours,
            settings.cookie_health_check_interval_hours,
            settings.scheduled_ad_interval_hours,
        )
    else:
        logger.warning("JobQueue is not available; daily reports and cookie health checks are not scheduled.")

    logger.info("POST_INIT finished")


def build_application():
    settings = load_settings()
    setup_logging(settings)

    logger.info("Application build started")
    logger.info("BOT_TOKEN exists=%s", bool(settings.bot_token))
    logger.info("ADMIN_IDS=%s", sorted(settings.admin_ids))
    logger.info("LOG_LEVEL=%s", settings.log_level)
    init_db(settings)
    logger.info("Database initialized")

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Add BOT_TOKEN to nano.env")

    builder = ApplicationBuilder().token(settings.bot_token)
    builder.post_init(post_init)

    if settings.use_local_bot_api:
        logger.info("Local Telegram Bot API mode enabled")

        builder.base_url(f"{settings.bot_api_base_url}/bot")
        builder.base_file_url(f"{settings.bot_api_base_url}/file/bot")
        builder.local_mode(True)

    app = builder.build()

    app.bot_data["settings"] = settings
    app.bot_data["pending_choices"] = {}

    # Логирует все апдейты и не мешает обычным хендлерам.
    app.add_handler(
        TypeHandler(Update, raw_update_logger, block=False),
        group=-1,
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("add_to_group", add_to_group_cmd))
    app.add_handler(CommandHandler("welcome_set", welcome_set_cmd))
    app.add_handler(CommandHandler("welcome_clear", welcome_clear_cmd))
    app.add_handler(CommandHandler("welcome_status", welcome_status_cmd))
    app.add_handler(ChatMemberHandler(bot_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(CommandHandler("debug_meta", debug_meta_cmd))
    app.add_handler(CommandHandler(["admin", "help_admin", "settings"], admin_panel_cmd))
    app.add_handler(CommandHandler("admin_run", admin_run_cmd))
    app.add_handler(CommandHandler("admin_list", admin_list_cmd))
    app.add_handler(CommandHandler("admin_add", admin_add_cmd))
    app.add_handler(CommandHandler("admin_del", admin_del_cmd))
    app.add_handler(CommandHandler("bot_status", bot_status_cmd))
    app.add_handler(CommandHandler("health_check", health_check_cmd))
    app.add_handler(CommandHandler("cleanup_temp", cleanup_temp_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("user", user_cmd))
    app.add_handler(CommandHandler("users_count", users_count_cmd))
    app.add_handler(CommandHandler("users_top", users_top_cmd))
    app.add_handler(CommandHandler("top_downloads", top_downloads_cmd))
    app.add_handler(CommandHandler("platform_stats", platform_stats_cmd))
    app.add_handler(CommandHandler("cache_stats", cache_stats_cmd))
    app.add_handler(CommandHandler("errors", errors_cmd))
    app.add_handler(CommandHandler("recent_downloads", recent_downloads_cmd))
    app.add_handler(CommandHandler("failed_downloads", failed_downloads_cmd))
    app.add_handler(CommandHandler("groups", groups_cmd))
    app.add_handler(CommandHandler("db_tables", db_tables_cmd))
    app.add_handler(CommandHandler("db_export", db_export_cmd))
    app.add_handler(CommandHandler("table_export", table_export_cmd))
    app.add_handler(CommandHandler("ad_overview", ad_overview_cmd))
    app.add_handler(CommandHandler("req_overview", req_overview_cmd))
    app.add_handler(CommandHandler("cookie_check", cookie_check_cmd))
    app.add_handler(CommandHandler("platform_health", platform_health_cmd))
    app.add_handler(CommandHandler("cookie_health", cookie_health_cmd))
    app.add_handler(CommandHandler("add_proxy", add_proxy_cmd))
    app.add_handler(CommandHandler("add_proxy_list", add_proxy_list_cmd))
    app.add_handler(CommandHandler("delete_all_proxy", delete_all_proxy_cmd))
    app.add_handler(CommandHandler("delete_one_proxy", delete_one_proxy_cmd))
    app.add_handler(CommandHandler("proxy_list", proxy_list_cmd))
    app.add_handler(CommandHandler("proxy_stats", proxy_stats_cmd))
    app.add_handler(CommandHandler("proxy_hs", proxy_hs_cmd))
    app.add_handler(CommandHandler("daily_report", daily_report_cmd))
    app.add_handler(CommandHandler("maintenance_on", maintenance_on_cmd))
    app.add_handler(CommandHandler("maintenance_off", maintenance_off_cmd))
    app.add_handler(CommandHandler("maintenance_status", maintenance_status_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("banned", banned_cmd))
    app.add_handler(CommandHandler("reports", reports_cmd))
    app.add_handler(CommandHandler("admin_receive_video_on", admin_receive_video_on_cmd))
    app.add_handler(CommandHandler("admin_receive_video_off", admin_receive_video_off_cmd))
    app.add_handler(CommandHandler("ad_add", ad_add_cmd))
    app.add_handler(CommandHandler("ad_del", ad_del_cmd))
    app.add_handler(CommandHandler("ad_list", ad_list_cmd))
    app.add_handler(CommandHandler("ad_stats", ad_stats_cmd))
    app.add_handler(CommandHandler("ad_stats_txt", ad_stats_txt_cmd))
    app.add_handler(CommandHandler(["ad_on", "ad_off"], ad_status_cmd))
    app.add_handler(CommandHandler(["ad8_add", "scheduled_ad_add"], ad8_add_cmd))
    app.add_handler(CommandHandler(["ad8_del", "scheduled_ad_del"], ad8_del_cmd))
    app.add_handler(CommandHandler(["ad8_list", "scheduled_ad_list"], ad8_list_cmd))
    app.add_handler(CommandHandler(["ad8_stats", "scheduled_ad_stats"], ad8_stats_cmd))
    app.add_handler(CommandHandler(["ad8_stats_txt", "scheduled_ad_stats_txt"], ad8_stats_txt_cmd))
    app.add_handler(CommandHandler(["ad8_on", "ad8_off", "scheduled_ad_on", "scheduled_ad_off"], ad8_status_cmd))
    app.add_handler(CommandHandler(["broadcast", "bc"], broadcast_cmd))
    app.add_handler(CommandHandler(["bc_users", "broadcast_users"], broadcast_users_cmd))
    app.add_handler(CommandHandler("friend_add", friend_add_cmd))
    app.add_handler(CommandHandler("friend_del", friend_del_cmd))
    app.add_handler(CommandHandler("friend_list", friend_list_cmd))
    app.add_handler(CommandHandler("req_add", req_add_cmd))
    app.add_handler(CommandHandler("req_del", req_del_cmd))
    app.add_handler(CommandHandler("req_list", req_list_cmd))
    app.add_handler(CommandHandler("req_list_txt", req_list_txt_cmd))
    app.add_handler(CommandHandler("req_stats", req_stats_cmd))
    app.add_handler(CommandHandler(["req_on", "req_off"], req_status_cmd))
    app.add_handler(CommandHandler("req_edit", req_edit_cmd))
    app.add_handler(CommandHandler("req_checker", req_checker_cmd))
    app.add_handler(CommandHandler("req_text", req_text_cmd))
    app.add_handler(CommandHandler(["help", "report_problem", "problem"], report_problem_cmd))
    app.add_handler(CommandHandler(["download", "dl"], link_message_handler))
    app.add_handler(CommandHandler(
        [
            "ccy_1", "ccy_2", "ccy_3",
            "cct_1", "cct_2", "cct_3",
            "cci_1", "cci_2", "cci_3",
            "ccp_1", "ccp_2", "ccp_3",
            "change_cookies_1", "change_cookies_2", "change_cookies_3",
        ],
        cookie_replace_cmd,
    ))
    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            admin_receive_video_message_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.REPLY & filters.Regex(r"(?i)^add(\s|$)"),
            ad_add_reply_text_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            pending_problem_report_message_handler,
        ),
        group=-2,
    )

    app.add_handler(
        CallbackQueryHandler(
            proxy_delete_callback_handler,
            pattern=f"^{PROXY_DELETE_CONFIRM_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            ad_click_callback_handler,
            pattern=f"^{AD_CLICK_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            required_open_callback_handler,
            pattern=f"^{REQUIRED_OPEN_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            required_check_callback_handler,
            pattern=f"^{REQUIRED_CHECK_CALLBACK}$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            legacy_youtube_quality_callback_handler,
            pattern=f"^{LEGACY_YOUTUBE_QUALITY_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            legacy_youtube_audio_callback_handler,
            pattern=f"^{LEGACY_YOUTUBE_AUDIO_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            legacy_youtube_back_callback_handler,
            pattern=f"^{LEGACY_YOUTUBE_BACK_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            language_callback_handler,
            pattern=f"^{LANGUAGE_CALLBACK_PREFIX}",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            youtube_quality_callback_handler,
            pattern=f"^{YOUTUBE_QUALITY_CALLBACK_PREFIX}",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            link_message_handler,
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            youtube_audio_callback_handler,
            pattern=f"^{YOUTUBE_AUDIO_CALLBACK_PREFIX}",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            youtube_shorts_audio_callback_handler,
            pattern=f"^{YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX}",
        )
    )
    
    app.add_error_handler(error_handler)

    logger.info("Handlers registered")
    logger.info("Application build finished")

    return app


def main() -> None:
    logger.info("main() called")

    app = build_application()

    logger.info("Downloader Bot V2 is starting polling")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
