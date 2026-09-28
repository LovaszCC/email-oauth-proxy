import ssl
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.crypto import Cryptographer
from app.db import Database


@pytest.fixture
def fernet_key() -> str:
    return Cryptographer.generate_key()


@pytest.fixture
def crypto(fernet_key) -> Cryptographer:
    return Cryptographer(fernet_key)


@pytest.fixture
async def db(tmp_path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_all()
    yield database
    await database.dispose()


@pytest.fixture(scope="session")
def tls_cert(tmp_path_factory) -> tuple[Path, Path]:
    """Self-signed cert for localhost, used by the fake upstream IMAP server."""
    directory = tmp_path_factory.mktemp("tls")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture(scope="session")
def server_ssl(tls_cert) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(str(tls_cert[0]), str(tls_cert[1]))
    return ctx


@pytest.fixture(scope="session")
def client_ssl(tls_cert) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(tls_cert[0]))
