"""Symmetric encryption for secrets at rest (Azure DevOps PATs, OAuth tokens).

The encryption key comes from the environment (PAT_ENCRYPTION_KEY), never
committed. Encrypted values are what gets stored in Postgres; plaintext
secrets never appear in logs, Celery task payloads, or API responses after
the initial submission.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


class SecretBox:
    def __init__(self, encryption_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()
