import asyncio
from collections import defaultdict


class AccountLocks:
    """One asyncio.Lock per account id, shared by the IMAP proxy and the background refresher
    so that a token refresh never runs twice concurrently for the same account."""

    def __init__(self) -> None:
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, account_id: int) -> asyncio.Lock:
        return self._locks[account_id]
