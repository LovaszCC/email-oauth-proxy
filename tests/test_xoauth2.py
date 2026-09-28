import base64

from app.proxy.xoauth2 import build_xoauth2_string, decode_xoauth2_error


def test_build_xoauth2_string():
    encoded = build_xoauth2_string("user@example.com", "tok")
    assert base64.b64decode(encoded) == b"user=user@example.com\x01auth=Bearer tok\x01\x01"


def test_decode_xoauth2_error_json():
    payload = base64.b64encode(b'{"status":"400","schemes":"Bearer","scope":"x"}').decode()
    assert decode_xoauth2_error(payload) == "status 400 (schemes: Bearer, scope: x)"


def test_decode_xoauth2_error_fallback():
    assert decode_xoauth2_error("not base64!") == "not base64!"
    assert decode_xoauth2_error(base64.b64encode(b"plain text").decode()) == "plain text"
    assert decode_xoauth2_error(base64.b64encode(b"[1,2]").decode()) == "[1,2]"
