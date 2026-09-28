import pytest

from app.crypto import Cryptographer


def test_roundtrip():
    c = Cryptographer(Cryptographer.generate_key())
    token = c.encrypt("secret")
    assert token != "secret"
    assert c.decrypt(token) == "secret"


def test_invalid_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Cryptographer("not-a-key")


def test_decrypt_with_wrong_key():
    a = Cryptographer(Cryptographer.generate_key())
    b = Cryptographer(Cryptographer.generate_key())
    with pytest.raises(ValueError, match="decrypt"):
        b.decrypt(a.encrypt("x"))
