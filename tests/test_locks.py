from app.services.locks import AccountLocks


def test_same_id_same_lock():
    locks = AccountLocks()
    assert locks.get(1) is locks.get(1)
    assert locks.get(1) is not locks.get(2)
