from enum import StrEnum

from volty.inverters.base import Credentials, InverterClient
from volty.inverters.luxpower.client import REGION_URLS, LuxpowerClient


class Brand(StrEnum):
    LUXPOWER = "luxpower"


def brand_regions(brand: Brand) -> tuple[str, ...]:
    match brand:
        case Brand.LUXPOWER:
            return tuple(REGION_URLS)


def create_client(brand: Brand, region: str, credentials: Credentials) -> InverterClient:
    match brand:
        case Brand.LUXPOWER:
            return LuxpowerClient(region, credentials)
