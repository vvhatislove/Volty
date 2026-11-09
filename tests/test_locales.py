from string import Formatter

from volty.bot.i18n import catalogs
from volty.inverters import Brand, brand_regions


def _placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(text) if field}


def test_every_language_has_the_same_keys_and_placeholders() -> None:
    english = catalogs()["en"]
    for catalog in catalogs().values():
        assert catalog.keys() == english.keys()
        for key, text in catalog.items():
            assert _placeholders(text) == _placeholders(english[key]), key


def test_every_brand_and_region_has_a_label() -> None:
    english = catalogs()["en"]
    for brand in Brand:
        assert f"brand.{brand}" in english
        assert f"connect.choose_region.{brand}" in english
        for region in brand_regions(brand):
            assert f"region.{brand}.{region}" in english
