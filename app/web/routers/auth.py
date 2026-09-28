import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.state import AppState
from app.web.deps import get_state
from app.web.forms import LoginForm
from app.web.templating import render

router = APIRouter()


@router.get("/login")
async def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
async def login(request: Request, state: AppState = Depends(get_state)):
    form = LoginForm.model_validate(dict(await request.form()))
    settings = state.settings
    user_ok = secrets.compare_digest(form.username.encode(), settings.admin_user.encode())
    password_ok = secrets.compare_digest(form.password.encode(), settings.admin_password.encode())
    if not (user_ok & password_ok):
        return render(request, "login.html", {"error": "Invalid username or password"}, 401)
    request.session["admin"] = True
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
