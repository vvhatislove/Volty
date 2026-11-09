from enum import StrEnum

from volty.inverters.base import Credentials, InverterClient
from volty.inverters.haipower.client import REGION_URLS as HAIPOWER_REGION_URLS
from volty.inverters.haipower.client import HaipowerClient
from volty.inverters.luxpower.client import REGION_URLS as LUXPOWER_REGION_URLS
from volty.inverters.luxpower.client import LuxpowerClient


class Brand(StrEnum):
    LUXPOWER = "luxpower"
    HAIPOWER = "haipower"


def brand_regions(brand: Brand) -> tuple[str, ...]:
    match brand:
        case Brand.LUXPOWER:
            return tuple(LUXPOWER_REGION_URLS)
        case Brand.HAIPOWER:
            return tuple(HAIPOWER_REGION_URLS)


def create_client(brand: Brand, region: str, credentials: Credentials) -> InverterClient:
    match brand:
        case Brand.LUXPOWER:
            return LuxpowerClient(region, credentials)
        case Brand.HAIPOWER:
            return HaipowerClient(region, credentials)
