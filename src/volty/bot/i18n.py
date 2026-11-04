import json
from importlib.resources import files

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "uk": "Українська", "ru": "Русский"}

_CATALOGS: dict[str, dict[str, str]] = {
    language: json.loads(
        files("volty.bot").joinpath("locales", f"{language}.json").read_text("utf-8")
    )
    for language in LANGUAGE_NAMES
}


def resolve_language(language_code: str | None) -> str:
    return language_code if language_code in _CATALOGS else DEFAULT_LANGUAGE


def all_translations(key: str) -> set[str]:
    return {catalog[key] for catalog in _CATALOGS.values()}


def catalogs() -> dict[str, dict[str, str]]:
    return _CATALOGS


class Translator:
    def __init__(self, language: str) -> None:
        self._catalog = _CATALOGS[resolve_language(language)]

    def __call__(self, key: str, **params: object) -> str:
        return self._catalog[key].format(**params)
