from titan.auth.passwords import hash_password, verify_password


def test_hash_and_verify():
    h = hash_password("uma senha boa")
    assert h.startswith("scrypt$")
    assert "uma senha boa" not in h
    assert verify_password("uma senha boa", h)
    assert not verify_password("outra", h)


def test_hashes_are_salted():
    assert hash_password("abc") != hash_password("abc")


def test_malformed_hash_rejected():
    assert not verify_password("x", "lixo")
    assert not verify_password("x", "bcrypt$1$2$3$4$5")
