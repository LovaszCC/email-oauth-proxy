from fastapi import Request


def flash(request: Request, message: str, category: str = "info") -> None:
    # Reassign instead of mutating in place: Starlette's Session only persists
    # changes it saw through __setitem__/pop/etc., not nested list mutations.
    messages = list(request.session.get("flash", []))
    messages.append({"message": message, "category": category})
    request.session["flash"] = messages


def pop_flash(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flash", [])
