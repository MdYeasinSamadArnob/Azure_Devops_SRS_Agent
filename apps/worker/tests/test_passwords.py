from srs_core.auth.passwords import hash_password, verify_password


def test_hash_and_verify_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hash_is_never_the_plaintext():
    hashed = hash_password("hunter2")
    assert hashed != "hunter2"
    assert "hunter2" not in hashed


def test_hash_is_salted_so_the_same_password_hashes_differently_each_time():
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_fails_closed_on_a_malformed_hash_instead_of_raising():
    # A DB row with a corrupt/foreign hash format must not turn every
    # login attempt into a 500 — this is the whole reason verify_password
    # catches ValueError internally rather than letting it propagate.
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False
