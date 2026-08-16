from functools import lru_cache

from srs_core.crypto import SecretBox

from src.config import get_settings


@lru_cache
def get_secret_box() -> SecretBox:
    return SecretBox(get_settings().pat_encryption_key)
