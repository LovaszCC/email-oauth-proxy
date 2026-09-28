from starlette.middleware.sessions import Session
from starlette.requests import Request

from app.web.flash import flash, pop_flash


def make_request(session: Session) -> Request:
    return Request({"type": "http", "session": session, "headers": []})


def test_second_flash_marks_session_modified():
    """Starlette only persists a session it saw modified at the top level."""
    session = Session({"flash": [{"message": "first", "category": "info"}]})
    session.modified = False
    request = make_request(session)
    flash(request, "second", "success")
    assert session.modified is True
    assert [m["message"] for m in pop_flash(request)] == ["first", "second"]
    assert pop_flash(request) == []
