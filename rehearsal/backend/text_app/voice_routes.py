"""Mount the team's Pipecat pipeline on a training-session WebSocket."""
import asyncio
import importlib.util
import logging

from fastapi import WebSocket, WebSocketDisconnect

from .budget import local_setting
from .store import Conflict
from .voice_training import VoiceTraining, validate_voice_session
from .avatar_profiles import selected_status
from .avatar_sessions import AvatarSessions
from .models import VoicePrepareRequest, VoiceStopRequest

logger = logging.getLogger(__name__)


def pipeline_status():
    installed = importlib.util.find_spec("pipecat") is not None
    enabled = local_setting("INWORLD_API_ENABLED", "0") == "1"
    key = bool(local_setting("INWORLD_API_KEY"))
    openai = bool(local_setting("OPENAI_API_KEY")) and local_setting("OPENAI_API_ENABLED", "0") == "1"
    return {"engine": "pipecat", "installed": installed, "enabled": enabled, "key_configured": key,
            "available": installed and enabled and key and openai,
            "voice": local_setting("INWORLD_VOICE_ID", "Svetlana"),
            "vad": "Silero VAD (server)", "turn_detection": "Smart Turn v3 (server)",
            "stt": "WhisperSTTService / faster-whisper (server)",
            "model": local_setting("WHISPER_MODEL", "small"), "used_requests": None,
            "local_only": True,
            "detail": "Готов к запуску; модели загружаются на сервере при первом подключении." if installed and enabled and key and openai
                      else "Нужны uv sync --extra voice, ключи OpenAI/Inworld и включение API в .env.local."}


def mount_voice(app, service):
    connections = {}
    app.state.voice_connections = connections
    avatars = AvatarSessions()
    app.state.avatar_sessions = avatars

    @app.on_event("shutdown")
    async def shutdown_avatars():
        for task, training in list(connections.values()):
            if training.worker:
                await training.worker.cancel()
            else:
                task.cancel()
        await avatars.close()

    @app.get("/api/text/pipeline/status")
    async def status():
        profile = service.store.settings().avatar_profile
        if profile == 'legacy_3d':
            return {**pipeline_status(), 'provider': 'Inworld'}
        info = selected_status(profile)
        return {**pipeline_status(), **info, 'provider': 'Cartesia',
                'enabled': info['available'], 'key_configured': not info['missing']}

    @app.post("/api/text/sessions/{sid}/voice/prepare")
    async def prepare(sid: str, request: VoicePrepareRequest | None = None):
        session = service.store.session(sid)
        validate_voice_session(session)
        profile = session.settings.avatar_profile
        if sid in connections:
            raise Conflict("Голосовой разговор уже подключён.")
        if profile != "legacy_3d":
            if request is None:
                raise Conflict("Для нового подключения нужен идентификатор попытки.")
            if request.audio_only and not session.settings.allow_audio_fallback:
                raise Conflict("Методист отключил резерв без видео.")
            status = selected_status(profile, audio_only=request.audio_only)
        else:
            status = pipeline_status()
        if not status["available"]:
            raise Conflict("Голос ещё не подключён администратором. Пока можно продолжить текстом.")
        if profile != "legacy_3d":
            return await avatars.prepare(sid, profile, request.request_id, audio_only=request.audio_only)
        return {"path": f"/api/text/sessions/{sid}/voice/ws"}

    @app.post("/api/text/sessions/{sid}/voice/stop")
    async def stop(sid: str, request: VoiceStopRequest | None = None):
        service.store.session(sid)
        lease = avatars.leases.get(sid)
        if request and lease and lease.request_id != request.request_id:
            return {"stopped": False, "reason": "Another connection owns this session"}
        entry = connections.get(sid)
        if entry:
            task, training = entry
            if training.worker:
                await training.worker.cancel()
            else:
                task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=8)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)
                except asyncio.TimeoutError:
                    raise Conflict("Голосовой сервер ещё останавливается. Повторите завершение через несколько секунд.")
            except (asyncio.CancelledError, Exception):
                pass
            if connections.get(sid) is entry:
                connections.pop(sid, None)
        await avatars.stop(sid, request.request_id if request else None)
        return {"stopped": True}

    @app.websocket("/api/text/sessions/{sid}/voice/ws")
    async def websocket(sid: str, ws: WebSocket):
        origin = ws.headers.get("origin", "")
        from urllib.parse import urlparse
        if urlparse(origin).hostname not in {"localhost", "127.0.0.1"}:
            await ws.close(code=1008)
            return
        try:
            session = service.store.session(sid)
            validate_voice_session(session)
            selected = session.settings.avatar_profile != "legacy_3d"
            if sid in connections:
                await ws.close(code=1008)
                return
            lease = avatars.claim(sid, ws.query_params.get("lease")) if selected else None
            if not selected and not pipeline_status()["available"]:
                await ws.close(code=1008)
                return
        except (KeyError, Conflict):
            await ws.close(code=1008)
            return
        training = VoiceTraining(service, sid)
        training.audio_only = bool(lease and lease.public["provider"] == "audio")
        async def execute():
            await ws.accept()
            from pipecat.runner.types import RunnerArguments
            from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport
            from backend.app.pipeline.transport import transport_params
            from backend.app.bot import run_bot
            transport = FastAPIWebsocketTransport(ws, transport_params["websocket"]())
            async with asyncio.timeout(avatars.max_seconds if selected else session.scenario.duration_minutes * 60):
                await run_bot(transport, RunnerArguments(), training=training)

        task = asyncio.create_task(execute())
        connections[sid] = (task, training)
        try:
            await task
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.error("Voice pipeline failed (%s); inspect server configuration", type(exc).__name__)
            try:
                await ws.close(code=1011, reason="Голосовой сервер недоступен. Проверьте модели и API.")
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            if connections.get(sid, (None,))[0] is task:
                connections.pop(sid, None)
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
            try:
                await avatars.stop(sid)
            except Exception:
                logger.error("Avatar cleanup needs explicit retry; new calls remain blocked")
