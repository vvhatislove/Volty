from string import Formatter

from volty.bot.i18n import catalogs
from volty.inverters.luxpower.client import REGION_URLS


def _placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(text) if field}


def test_every_language_has_the_same_keys_and_placeholders() -> None:
    english = catalogs()["en"]
    for catalog in catalogs().values():
        assert catalog.keys() == english.keys()
        for key, text in catalog.items():
            assert _placeholders(text) == _placeholders(english[key]), key


def test_every_region_has_a_label() -> None:
    for region in REGION_URLS:
        assert f"region.{region}" in catalogs()["en"]
