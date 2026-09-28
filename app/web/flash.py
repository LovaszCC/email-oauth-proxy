from fastapi import Request


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("flash", []).append({"message": message, "category": category})


def pop_flash(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flash", [])
