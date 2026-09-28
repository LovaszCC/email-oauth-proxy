import base64
import binascii
import json


def build_xoauth2_string(email: str, access_token: str) -> str:
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()


def decode_xoauth2_error(payload: str) -> str:
    """Decode the base64 JSON sent in the `+` continuation after a failed XOAUTH2."""
    try:
        text = base64.b64decode(payload, validate=True).decode(errors="replace")
    except (binascii.Error, ValueError):
        return payload
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict):
        return text
    status = data.pop("status", "unknown")
    details = ", ".join(f"{key}: {value}" for key, value in data.items())
    return f"status {status} ({details})" if details else f"status {status}"
