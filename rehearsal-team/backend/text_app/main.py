from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .budget import OpenAIRequestBudget
from .agent import Agent, AgentError
from .models import CancelRequest, ReviewRequest, Scenario, ScenarioDraft, ScenarioUpdate, Session, Settings, SpeechRequest, StartRequest, TurnRequest, now
from .seeds import seed
from .service import Service, scenario_view, session_view
from .store import Conflict, Store
from .models import PresentationSettings
from .avatar_profiles import public_profiles, selected_status

ROOT = Path(__file__).resolve().parents[2]


def create_app(*, store=None, agent=None):
    store = store or Store(Path(os.getenv("TEXT_TRAINER_DB", str(ROOT / "artifacts/text_workspace.sqlite3"))))
    seed(store)
    agent = agent or Agent(OpenAIRequestBudget.from_local_config())
    service = Service(store, agent)
    app = FastAPI(title="Репетиция · Pipecat и тренировки")
    app.state.service = service
    from .voice_routes import mount_voice
    mount_voice(app, service)
    # Local demonstration only. Role selection is not authentication.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in {
            "http://127.0.0.1:5174", "http://localhost:5174", "http://127.0.0.1:8001", "http://localhost:8001",
            "http://127.0.0.1:5175", "http://localhost:5175", "http://127.0.0.1:8002", "http://localhost:8002",
            "http://127.0.0.1:5176", "http://localhost:5176", "http://127.0.0.1:8003", "http://localhost:8003",
            "http://127.0.0.1:5177", "http://localhost:5177", "http://127.0.0.1:8004", "http://localhost:8004",
        }:
            return JSONResponse(status_code=403, content={"detail": "Запрос с другого сайта отклонён."})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Сценарий или тренировка не найдены."})

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AgentError)
    async def agent_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/api/text/bootstrap")
    async def bootstrap(role: Literal["participant", "methodist", "admin"] = "participant"):
        staff = role != "participant"
        scenarios = [Scenario.model_validate(raw) for raw in store.all("scenario")]
        sessions = [Session.model_validate(raw) for raw in store.all("session")]
        settings = store.settings()
        if not staff and settings.voice_mode == 'avatar' and settings.avatar_profile != 'legacy_3d':
            from .avatar_profiles import PROFILES
            scenarios = [s.model_copy(update={'npc_name': PROFILES[settings.avatar_profile]['title']}) for s in scenarios]
        result = {
            "scenarios": [scenario_view(s, staff) for s in scenarios if staff or s.status == "published"],
            "sessions": [{"id": s.id, "title": s.scenario.title, "participant": s.participant, "status": s.status,
                          "created_at": s.created_at, "score": s.report.overall_score if s.report else None,
                          "reviewed": s.reviewed, "report_status": s.report_status, "is_demo": s.settings.provider == "demo",
                          "covered": s.report.covered if s.report else 0, "total": len(s.scenario.criteria),
                          "turns": sum(t.status == "committed" for t in s.turns)} for s in sessions],
            "runtime": {"external_processing": settings.provider == "openai", "is_demo": settings.provider == "demo", "mode": settings.mode, "voice_mode": settings.voice_mode},
            "local_demo": True,
        }
        if role == "admin":
            status = agent.budget.status()
            result["settings"] = settings.model_dump()
            result["budget"] = status
        if staff:
            result["presentation"] = {k: getattr(settings, k) for k in PresentationSettings.model_fields}
            result["avatar_profiles"] = public_profiles()
            result["avatar_status"] = {"legacy_3d": selected_status("legacy_3d")}
        return result

    @app.put("/api/text/presentation")
    async def update_presentation(request: PresentationSettings):
        current = store.settings()
        try:
            store.get("settings", "main")
        except KeyError:
            store.put("settings", "main", current)
        updated = current.model_copy(update={**request.model_dump(), "revision": request.revision + 1})
        store.put("settings", "main", updated, expected_revision=request.revision)
        return {k: getattr(updated, k) for k in PresentationSettings.model_fields}

    @app.post("/api/text/scenarios")
    async def create_scenario(request: ScenarioDraft):
        scenario = Scenario(**request.model_dump(), id=str(uuid4()))
        store.put("scenario", scenario.id, scenario)
        return scenario_view(scenario, True)

    @app.put("/api/text/scenarios/{sid}")
    async def update_scenario(sid: str, request: ScenarioUpdate):
        store.scenario(sid)
        scenario = Scenario(**request.model_dump(exclude={"revision"}), id=sid, revision=request.revision + 1, updated_at=now())
        store.put("scenario", sid, scenario, expected_revision=request.revision)
        return scenario_view(scenario, True)

    @app.put("/api/text/settings")
    async def update_settings(request: Settings):
        try:
            store.get("settings", "main")
        except KeyError:
            store.put("settings", "main", Settings())
        updated = request.model_copy(update={"revision": request.revision + 1})
        store.put("settings", "main", updated, expected_revision=request.revision)
        return updated

    @app.post("/api/text/sessions")
    async def start(request: StartRequest):
        return session_view(await service.start(request))

    @app.get("/api/text/sessions/{sid}")
    async def get_session(sid: str, staff: bool = False):
        return session_view(store.session(sid), staff)

    @app.post("/api/text/sessions/{sid}/turns")
    async def turn(sid: str, request: TurnRequest):
        if sid in app.state.voice_connections or sid in app.state.avatar_sessions.leases:
            raise Conflict("Сначала отключите голосовой разговор перед переходом к тексту.")
        return session_view(await service.turn(sid, request))

    @app.post("/api/text/sessions/{sid}/cancel")
    async def cancel(sid: str, request: CancelRequest):
        return session_view(await service.cancel(sid, request.request_id))

    @app.post("/api/text/sessions/{sid}/end")
    async def end(sid: str):
        if sid in app.state.voice_connections or sid in app.state.avatar_sessions.leases:
            raise Conflict("Сначала остановите голосовой разговор, затем получите разбор.")
        return session_view(await service.end(sid))

    @app.post("/api/text/sessions/{sid}/report")
    async def retry_report(sid: str):
        if store.session(sid).status != "completed":
            raise Conflict("Сначала завершите тренировку.")
        return session_view(await service.end(sid, retry=True))

    @app.put("/api/text/sessions/{sid}/review")
    async def review(sid: str, request: ReviewRequest):
        async with service.locks[sid]:
            session = store.session(sid)
            if session.status != "completed":
                raise Conflict("Дождитесь завершения тренировки.")
            session.review_note, session.reviewed = request.note, request.reviewed
            service.save(session)
            return session_view(session, True)

    return app


app = create_app()
