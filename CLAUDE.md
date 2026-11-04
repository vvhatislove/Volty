# Volty

Volty is an open-source Telegram bot for managing and monitoring solar inverters. Anyone can use the official bot or self-host their own instance, then connect their own inverters. LuxPower is the first supported brand, with data read from its cloud service.

## Language

- Write READMEs and other documentation in English.
- Write commit messages in English.
- The bot speaks English, Ukrainian, and Russian. Keep all user-facing text in translation files from the start.

## Python and tooling

- Use the latest stable Python release (currently 3.15).
- Manage dependencies and the Python version with `uv` and `pyproject.toml`. Commit the lock file.
- Use `ruff` for linting and formatting.
- Type everything and keep the type checker in strict mode.
- Use `async` code for all network I/O.
- Use `aiogram` 3 for the Telegram bot.
- Use PostgreSQL with async SQLAlchemy, and Alembic for migrations.
- Run the bot and PostgreSQL with Docker Compose, locally and on servers.
- Run `ruff`, the type checker, and `pytest` in GitHub Actions on every push and pull request.

## Architecture

- The bot and core logic depend only on a shared inverter interface.
- Each brand lives in its own adapter module. Adding a brand means adding an adapter, without changing the core.
- The LuxPower adapter talks to the cloud through our own thin `httpx` client, not a third-party library.

## Bot UX

- The bot works through buttons. `/start` is the only command, because Telegram requires it.
- Credentials and settings are handled only in private chats. In a group the bot only links itself when the inverter's owner adds it, and posts alerts.

## Code style

- Write clean, readable code.
- Avoid unnecessary comments. Add one only when a decision really needs explaining.

## Testing

- Use `pytest`.
- Run tests against recorded, anonymized cloud responses. Tests never call the real LuxPower service.

## Secrets

- Users send their cloud login and password to the bot in a chat message. The bot deletes that message as soon as it reads it.
- Store each user's inverter credentials encrypted in the project database, never in plaintext.
- Keep the encryption key and the bot token outside the database, in environment variables.
- Never commit, log, or put in test data any credentials, tokens, or real inverter serial numbers.

## Power alerts

- Alert only after two consecutive readings confirm a change between grid on and grid off.
- An offline inverter or an unrecognized status means the grid state is unknown. It never triggers an alert.
- After the cloud rejects saved credentials on two polls in a row, stop polling that account until the user reconnects, so the cloud doesn't lock it.

## Inverter control

- The first stage is read-only: read data, do not change inverter settings.
- When write commands are added, send them to a real inverter only after the user explicitly confirms each one.

## Open source

- The license is Apache-2.0.
- The `NOTICE` file credits the original author and links to the original repository.

## Git

- Use Conventional Commits (`feat:`, `fix:`, `docs:`), with one logical change per commit.
- Commit or push only when the user asks.

## Commands

- Check everything: `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest`
- Add a migration: `uv run alembic revision -m "..."`. Write it by hand and confirm with `uv run alembic check`.
- Run the bot: `docker compose up -d --build`
