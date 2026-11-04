from collections.abc import Callable

from volty.crypto import CredentialCipher
from volty.inverters import Brand, create_client
from volty.inverters.base import Credentials, InverterClient
from volty.storage.models import Account

ClientFactory = Callable[[Brand, str, Credentials], InverterClient]


class ClientPool:
    """Keeps one client per account so its cloud session survives between polls."""

    def __init__(self, cipher: CredentialCipher, factory: ClientFactory = create_client) -> None:
        self._cipher = cipher
        self._factory = factory
        self._clients: dict[int, tuple[bytes, InverterClient]] = {}

    async def get(self, account: Account) -> InverterClient:
        cached = self._clients.get(account.id)
        if cached is not None:
            token, client = cached
            if token == account.encrypted_credentials:
                return client
            await client.aclose()
        credentials = self._cipher.decrypt(account.encrypted_credentials)
        client = self._factory(account.brand, account.region, credentials)
        self._clients[account.id] = (account.encrypted_credentials, client)
        return client

    async def discard(self, account_id: int) -> None:
        cached = self._clients.pop(account_id, None)
        if cached is not None:
            await cached[1].aclose()

    async def aclose(self) -> None:
        for account_id in list(self._clients):
            await self.discard(account_id)
