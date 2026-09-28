from cryptography.fernet import Fernet, InvalidToken


class Cryptographer:
    """Encrypts secrets at rest with a Fernet key taken from SECRET_KEY."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except ValueError as exc:
            raise ValueError("SECRET_KEY must be a valid Fernet key") from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt value with the configured SECRET_KEY") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()
