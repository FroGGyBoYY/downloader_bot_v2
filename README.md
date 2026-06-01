# Downloader Bot v2

Telegram-бот для скачивания и отправки медиа из TikTok, YouTube, YouTube Music, Instagram, Pinterest и других поддержанных источников.

Бот умеет:

- принимать ссылки в личных чатах и группах;
- скачивать видео, фото, сторис, рилсы, shorts и музыкальные ссылки YouTube Music;
- отдавать YouTube-видео с выбором качества и аудиодорожки;
- кешировать отправленные файлы через Telegram `file_id`;
- работать с cookies-ротацией и прокси-пулом;
- показывать рекламу после скачивания и рекламу каждые 8 часов;
- проверять обязательные подписки;
- вести SQLite-базу пользователей, скачиваний, кеша, ошибок и рекламы;
- давать админ-панель, рассылки, отчеты и статистику.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

На Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Минимально нужны:

- `BOT_TOKEN` от BotFather;
- `ADMIN_IDS` через запятую;
- `DB_PATH`, по умолчанию `data/bot_v2.db`;
- `ffmpeg` и `ffprobe` в `PATH`;
- cookies-файлы в `secrets/cookies/`, если нужны авторизованные источники.

## Audio API для нового музыкального бота

Старый бот также может работать как локальный backend для `spotify_savers_bot`.

Запуск:

```bash
python audio_api.py
```

Параметры:

```env
AUDIO_API_HOST=127.0.0.1
AUDIO_API_PORT=8088
AUDIO_API_TOKEN=change-me
```

В новом боте указывается:

```env
AUTHORIZED_AUDIO_API_URL=http://127.0.0.1:8088/audio
AUTHORIZED_AUDIO_API_TOKEN=change-me
```

Audio API принимает метаданные трека, ищет подходящий источник через YouTube Music/yt-dlp, скачивает аудио и возвращает файл новому боту. Endpoint должен быть доступен только локально или через защищенную сеть.

## Группы

В группах старый бот вызывается командами:

```text
/download <ссылка>
/dl <ссылка>
```

Обычные ссылки в личке обрабатываются без команды.

## Прокси и cookies

Для YouTube/YouTube Music поддержаны:

- cookies-слоты;
- proxy pool;
- автоматическое переключение на следующую прокси;
- уведомления админам, когда cookies или прокси перестают работать.

Основные команды прокси:

```text
/add_proxy
/add_proxy_list
/proxy_list
/proxy_stats
/proxy_hs
/delete_one_proxy
/delete_all_proxy
```

Файлы с cookies и прокси не должны попадать в GitHub. Для этого они лежат в `secrets/`, `data/` или добавлены в `.gitignore`.

## Админ-команды

Часть команд можно запускать по номеру:

```text
/admin_run 1
```

Основные команды:

```text
/bot_status
/health_check
/users_count
/users_top
/top_downloads
/platform_stats
/cache_stats
/errors
/recent_downloads
/failed_downloads
/db_tables
/db_export
/table_export users
/ad_overview
/req_overview
/admin_list
/admin_add 123456789
/admin_del 123456789
/friend_add 123456789
/friend_del 123456789
/friend_list
/platform_health
/daily_report
/maintenance_on [text]
/maintenance_off
/maintenance_status
/ban 123456789
/unban 123456789
/banned
/reports
/ad8_list
/broadcast
/bc
/welcome_set
/welcome_status
/welcome_clear
/cleanup_temp 24
/users
/user 123456789
```

## Что не хранить в репозитории

Не коммитить:

- `.env`, `nano.env` и их backup-файлы;
- SQLite-базы из `data/`;
- `logs/`;
- `media/`;
- cookies;
- proxy-листы;
- SSH-ключи и любые токены.

## Production

На VPS обычно запускаются два процесса:

- основной Telegram bot service;
- локальный `audio_api.py` service для музыкального backend.

Перед перезапуском проверяйте:

```bash
systemctl status downloader-bot.service
systemctl status downloader-audio-api.service
journalctl -u downloader-bot.service -n 100 --no-pager
journalctl -u downloader-audio-api.service -n 100 --no-pager
```
