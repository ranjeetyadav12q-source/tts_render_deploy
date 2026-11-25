# Ultimate TTS Telegram Bot — Render deployment

## Included
- Pyrogram Telegram bot
- EPUB, DOCX and TXT to Hindi MP3 using Edge TTS
- FFmpeg audio joining and optional BGM mixing
- Membership approval, expiry checks, admin controls and per-user daily quota
- Render background worker + persistent disk configuration

## Before deploying
The source file contained Telegram API credentials and a bot token. Those credentials must be considered exposed. Revoke/regenerate the bot token with @BotFather and rotate the Telegram API hash if possible. Do not reuse the exposed token.

## Deploy
1. Create a GitHub repository and upload all files in this folder (not `bot_original.txt`).
2. In Render choose **New → Blueprint**, connect that GitHub repository, and let Render read `render.yaml`.
3. Enter `API_ID`, `API_HASH`, `BOT_TOKEN`, and `ADMIN_ID` in the Render environment prompt/dashboard.
4. Deploy the background worker. Check its Logs for `Render TTS Bot started`.
5. Open your Telegram bot and send `/start`.

## Important
- This is a **background worker**, not a web service. Telegram long polling does not need a public URL.
- The `starter` worker and persistent disk are paid Render resources; a free web service is not a reliable always-on host for this polling bot.
- The persistent disk keeps `users_db.json`, BGM files and Pyrogram session data across deploys. Keep one worker instance only because the local JSON database is not designed for concurrent replicas.
- `CONCURRENCY_LIMIT=15` is retained from the original code. Reduce it if the worker runs out of memory or Edge TTS requests are throttled.
- `bot_original.txt` is only a backup of the uploaded source. Do not upload it to the public repository because it contains exposed credentials.
