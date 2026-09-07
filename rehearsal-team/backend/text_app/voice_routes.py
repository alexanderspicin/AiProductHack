"""Local training WebSocket for the original AiProductHack pipeline."""
import asyncio
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from fastapi import WebSocket, WebSocketDisconnect
from .budget import local_setting
from .store import Conflict
from .voice_training import VoiceTraining, validate_voice_session

logger = logging.getLogger(__name__)


def pipeline_status():
    installed = importlib.util.find_spec("pipecat") is not None
    missing = [p for p in ("OPENAI", "INWORLD") if not local_setting(p + "_API_KEY") or local_setting(p + "_API_ENABLED", "0") != "1"]
    source = Path(__file__).resolve().parents[3] / "backend/app/bot.py"
    return {"engine": "pipecat", "source": "../backend/app (AiProductHack)", "installed": installed,
            "available": installed and source.is_file() and not missing, "enabled": not missing,
            "key_configured": bool(local_setting("INWORLD_API_KEY")), "provider": "Inworld", "missing": missing,
            "voice": local_setting("INWORLD_VOICE_ID", "Svetlana"), "vad": "Silero VAD (server)",
            "turn_detection": "Smart Turn v3 ONNX (server)", "stt": "faster-whisper (server)",
            "model": local_setting("WHISPER_MODEL", "small"), "local_only": False,
            "detail": "Бэкенд команды. Модели прогреваются при первом подключении." if not missing and installed and source.is_file()
                      else "Проверьте полный репозиторий, uv sync --extra voice и ключи OpenAI/Inworld в .env.local."}


def mount_voice(app, service):
    connections = {}
    app.state.voice_connections = connections
    app.state.avatar_sessions = SimpleNamespace(leases={})

    async def stop_session(sid):
        entry = connections.get(sid)
        if not entry:
            return
        task, training = entry
        if training.worker:
            await training.worker.cancel()
        else:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), 8)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
            except asyncio.TimeoutError:
                raise Conflict("Голос ещё останавливается. Повторите завершение через несколько секунд.")
        except (asyncio.CancelledError, Exception):
            pass
        if connections.get(sid) is entry:
            connections.pop(sid, None)

    @app.on_event("shutdown")
    async def shutdown():
        for sid in list(connections):
            await stop_session(sid)

    @app.get("/api/text/pipeline/status")
    async def status():
        return pipeline_status()

    @app.post("/api/text/sessions/{sid}/voice/prepare")
    async def prepare(sid: str):
        validate_voice_session(service.store.session(sid))
        if connections:
            raise Conflict("На этом локальном стенде уже идёт разговор. Сначала остановите его.")
        if not pipeline_status()["available"]:
            raise Conflict("Нужны зависимости voice и включённые ключи OpenAI/Inworld. Переписка остаётся доступна.")
        return {"path": f"/api/text/sessions/{sid}/voice/ws"}

    @app.post("/api/text/sessions/{sid}/voice/stop")
    async def stop(sid: str):
        service.store.session(sid)
        await stop_session(sid)
        return {"stopped": True}

    @app.websocket("/api/text/sessions/{sid}/voice/ws")
    async def websocket(sid: str, ws: WebSocket):
        if urlparse(ws.headers.get("origin", "")).hostname not in {"localhost", "127.0.0.1"}:
            await ws.close(code=1008); return
        try:
            session = service.store.session(sid)
            validate_voice_session(session)
            if connections or not pipeline_status()["available"]:
                await ws.close(code=1008); return
        except (KeyError, Conflict):
            await ws.close(code=1008); return
        training = VoiceTraining(service, sid)

        async def execute():
            await ws.accept()
            from .team_pipeline import run_bot, transport_params
            from pipecat.runner.types import RunnerArguments
            from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport
            transport = FastAPIWebsocketTransport(ws, transport_params["websocket"]())
            async with asyncio.timeout(session.scenario.duration_minutes * 60):
                await run_bot(transport, RunnerArguments(), training)

        task = asyncio.create_task(execute())
        connections[sid] = (task, training)
        try:
            await task
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.error("Team pipeline failed: %s", type(exc).__name__)
            try:
                await ws.close(code=1011, reason="Проверьте локальные модели и ключи OpenAI/Inworld.")
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            if connections.get(sid, (None,))[0] is task:
                connections.pop(sid, None)
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
