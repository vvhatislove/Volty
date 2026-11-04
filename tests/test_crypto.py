from volty.crypto import CredentialCipher
from volty.inverters.base import Credentials


def test_credentials_round_trip_and_are_not_stored_in_plaintext(cipher: CredentialCipher) -> None:
    credentials = Credentials(login="user@example.com", password="hunter2")

    token = cipher.encrypt(credentials)

    assert b"hunter2" not in token
    assert b"user@example.com" not in token
    assert cipher.decrypt(token) == credentials


def test_password_is_hidden_from_repr() -> None:
    assert "hunter2" not in repr(Credentials(login="user", password="hunter2"))
