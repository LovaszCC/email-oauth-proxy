from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.state import AppState
from app.web.deps import get_state, require_admin
from app.web.dto import LogEntryDto, LogsDto
from app.web.forms import LogFilterForm, parse_form
from app.web.templating import render

router = APIRouter(dependencies=[Depends(require_admin)])

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def _collect(state: AppState, form: LogFilterForm) -> LogsDto:
    entries = state.logs.entries(min_level=form.min_level, query=form.q, limit=form.limit)
    return LogsDto(
        count=len(entries),
        buffered=len(state.logs),
        capacity=state.logs.capacity,
        entries=[LogEntryDto.from_entry(e) for e in entries],
    )


@router.get("/logs")
async def logs_page(request: Request, state: AppState = Depends(get_state)):
    raw = dict(request.query_params)
    form, errors = parse_form(LogFilterForm, raw)
    if form is None:
        context = {
            "values": raw,
            "errors": errors,
            "levels": LEVELS,
            "logs": None,
            "refresh": False,
        }
        return render(request, "logs.html", context, status_code=422)
    context = {
        "values": {"level": form.level, "q": form.q, "limit": form.limit},
        "errors": {},
        "levels": LEVELS,
        "logs": _collect(state, form),
        "refresh": form.refresh,
    }
    return render(request, "logs.html", context)


@router.get("/api/logs", response_model=LogsDto)
async def logs_api(request: Request, state: AppState = Depends(get_state)):
    form, errors = parse_form(LogFilterForm, dict(request.query_params))
    if form is None:
        return JSONResponse({"errors": errors}, status_code=422)
    return _collect(state, form)
