"""One-way password hashing — deliberately separate from `srs_core.crypto`,
which is reversible (Fernet) encryption for secrets the system needs back
in plaintext (Azure PATs). A password must never be recoverable even by
the system itself, only verifiable, so it needs a different primitive:
bcrypt (salted, one-way, tunable work factor).
"""

from __future__ import annotations

import bcrypt

_ROUNDS = 12


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # A malformed/foreign hash (e.g. schema drift) must fail closed,
        # not raise into a 500 on every login attempt.
        return False
