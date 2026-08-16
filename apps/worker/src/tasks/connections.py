"""Decrypts an AzureConnection's PAT at the point of use only. The worker
receives a connection_id from the API — never the PAT itself, since Celery
task arguments are serialized through Redis in plaintext by default.
"""

from srs_core.crypto import SecretBox
from srs_core.db.models import AzureConnection
from sqlalchemy.orm import Session

from src.config import get_worker_settings


def resolve_pat(session: Session, connection_id: str) -> tuple[str, str, str]:
    """Returns (pat, azure_org, azure_project) for a connection_id."""
    connection = session.get(AzureConnection, connection_id)
    if connection is None:
        raise ValueError(f"azure_connection {connection_id} not found")
    if connection.auth_type != "pat" or not connection.encrypted_pat:
        raise ValueError(f"azure_connection {connection_id} has no usable PAT")
    box = SecretBox(get_worker_settings().pat_encryption_key)
    pat = box.decrypt(connection.encrypted_pat)
    return pat, connection.azure_org, connection.azure_project
