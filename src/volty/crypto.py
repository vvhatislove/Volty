import json

from cryptography.fernet import Fernet

from volty.inverters.base import Credentials


class CredentialCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, credentials: Credentials) -> bytes:
        payload = {"login": credentials.login, "password": credentials.password}
        return self._fernet.encrypt(json.dumps(payload).encode())

    def decrypt(self, token: bytes) -> Credentials:
        payload = json.loads(self._fernet.decrypt(token))
        return Credentials(login=payload["login"], password=payload["password"])
