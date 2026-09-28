from collections.abc import AsyncIterator

import pytest

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
