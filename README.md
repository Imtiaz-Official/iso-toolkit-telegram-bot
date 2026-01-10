# ISO Toolkit Keep-Alive Bot

A Telegram bot that keeps your Render deployment alive with automatic pings and manual controls.

## Features

- ⏰ **Auto-ping**: Automatically pings your site every 10 minutes to prevent spin-down
- 🔄 **Manual wake-up**: Wake your site manually when it's spun down
- 📊 **Statistics**: Track ping success rates and uptime
- ⚠️ **Alerts**: Get notified when pings fail (optional)

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with command list |
| `/help` | Show help message |
| `/check` | Check if site is online |
| `/wake` | Wake up the site (useful after spin-down) |
| `/status` | Show current bot and site status |
| `/stats` | Show ping statistics |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from [@BotFather](https://t.me/BotFather) | Required |
| `TARGET_URL` | URL to ping | `https://iso-toolkit.onrender.com/` |
| `OWNER_CHAT_ID` | Your Telegram chat ID for failure alerts | Optional |

## Quick Start

### 1. Create Your Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow instructions to name your bot
4. Copy the bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Click the button above or go to [dashboard.render.com](https://dashboard.render.com)
2. Click **"New +"** → **"Worker"**
3. Connect this GitHub repository
4. Render will auto-detect settings from `render.yaml`
5. Click **"Deploy"**

### 3. Start Using Your Bot

1. Open Telegram and search for your bot
2. Send `/start` to begin
3. Try `/check` to verify it's working

## Alternative Deployments

### Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/Imtiaz-Official/iso-toolkit-telegram-bot)

### Zeabur

1. Go to [zeabur.com](https://zeabur.com)
2. Create new project → Import from GitHub
3. Select this repository
4. Deploy!

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
TELEGRAM_BOT_TOKEN=your_token_here TARGET_URL=your_url_here python bot.py
```

## How It Works

The bot runs in the background and:

1. **Every 10 minutes**: Sends a GET request to your `TARGET_URL`
2. **On success**: Logs the ping and updates statistics
3. **On failure**: Logs the error and optionally sends you an alert

This keeps your free Render deployment from spinning down after 15 minutes of inactivity.

## Troubleshooting

**Bot not responding?**
- Check the logs on your hosting platform
- Verify `TELEGRAM_BOT_TOKEN` is correct
- Make sure the bot is deployed as a **Worker** (not Web Service)

**Site still spinning down?**
- Verify the `TARGET_URL` is correct
- Check `/stats` to see if pings are succeeding
- Make sure the bot is running (no crashes in logs)

**Not receiving alerts?**
- Add your chat ID as `OWNER_CHAT_ID` environment variable
- Find your chat ID by messaging [@userinfobot](https://t.me/userinfobot) on Telegram

## License

MIT License - feel free to use and modify!

## Support

For issues or questions:
- Open an issue on GitHub
- Check the [Render documentation](https://render.com/docs)
- Check the [python-telegram-bot documentation](https://python-telegram-bot.readthedocs.io/)
