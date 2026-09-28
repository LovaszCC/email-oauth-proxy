from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web.flash import pop_flash

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(
    request: Request, name: str, context: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    full_context = {
        "flash_messages": pop_flash(request),
        "admin": bool(request.session.get("admin")),
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, full_context, status_code=status_code)
