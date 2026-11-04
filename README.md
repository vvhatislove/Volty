# Volty

Volty is an open-source Telegram bot for monitoring solar inverters. It tells you when the grid goes down and when it comes back, and shows your battery charge and voltage. You use it with buttons, so there are no commands to remember.

LuxPower is the first supported brand, with data read from its cloud service. Volty only reads data for now and does not change inverter settings.

## Run your own bot

You need Docker and a bot token from [@BotFather](https://t.me/BotFather).

1. Copy the example settings:

   ```bash
   cp .env.example .env
   ```

2. Fill in `BOT_TOKEN`, `ENCRYPTION_KEY`, and `POSTGRES_PASSWORD` in `.env`. The file explains how to generate the key.

3. Start the bot and the database:

   ```bash
   docker compose up -d --build
   ```

4. Open your bot in Telegram, press **Start**, and connect your inverter.

Keep `ENCRYPTION_KEY` safe. Saved cloud passwords can't be decrypted without it, so if you lose it, every user has to connect again.

## How power alerts work

Volty polls the cloud every 60 seconds by default, and sends an alert after two readings in a row show the same change. An alert usually arrives within two minutes.

The inverter reports through its Wi-Fi dongle and your router. If the router loses power in an outage, the cloud stops getting data, so Volty can't tell that the grid went down. Put your router on backup power to get outage alerts.

Under **🔔 Notifications** you choose where alerts go for each inverter: direct messages, a group, or both. To use a group, tap **Add to a group** and pick it in Telegram. Under **⚙️ Settings** you can give an inverter a clear name, such as Home.

Under **⚙️ Settings → 🪫 Low battery alert** you set which voltage counts as 100% and 0%, and the charge level for the alert. The bot then works out the charge from this scale everywhere, so it may differ from the LuxPower site. **📊 Summary** shows today's energy and recent outages, and can post them to your group when you press the button.

In a linked group, every member can check the battery and summary with the buttons under alerts, or by sending `/start@your_bot` to get those buttons. Only the owner can change anything, in a private chat with the bot.

To see what your inverter reports, set `LOG_LEVEL=DEBUG` in `.env`. Each poll then logs its status code.

## Security

Users send their cloud login and password to the bot in chat. The bot deletes those messages right after reading them and stores the credentials encrypted. They still pass through Telegram like any other message, and whoever runs the bot holds the encryption key. Use a bot you trust, or run your own.

## Development

Volty needs [uv](https://docs.astral.sh/uv/). It installs the right Python version for you.

```bash
uv sync
```

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
```

## License

Volty is licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
