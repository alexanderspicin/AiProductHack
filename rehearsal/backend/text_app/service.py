from __future__ import annotations

import asyncio
from collections import defaultdict
from time import perf_counter
from uuid import uuid4

from .agent import Agent, AgentError
from .models import Session, StartRequest, Turn, TurnRequest, now
from .progress import covered_stages, record_goals
from .store import Conflict, Store


class Service:
    def __init__(self, store: Store, agent: Agent):
        self.store, self.agent = store, agent
        self.locks = defaultdict(asyncio.Lock)
        self.tasks: dict[tuple[str, str], asyncio.Task] = {}
        store.recover()

    async def start(self, request: StartRequest) -> Session:
        async with self.locks["starts"]:
            existing = self.store.find_start(request.request_id)
            if existing:
                session = self.store.session(existing)
                if (session.scenario.id != request.scenario_id or session.participant != request.participant
                        or session.voice_consent != request.voice_consent):
                    raise Conflict("Этот идентификатор запуска уже использован.")
                return session
            scenario = self.store.scenario(request.scenario_id)
            if scenario.status != "published":
                raise Conflict("Сценарий пока не опубликован. Методист должен опубликовать его перед тренировкой.")
            settings = self.store.settings()
            if settings.provider == "openai" and not request.consent:
                raise Conflict("Подтвердите отправку учебного диалога во внешний API.")
            if settings.voice_mode == "avatar" and not request.voice_consent:
                raise Conflict("Подтвердите передачу ответов персонажа в сервисы голоса и видео.")
            source_name = scenario.npc_name
            from .seeds import with_public_situation
            scenario = with_public_situation(scenario)
            if settings.voice_mode == "avatar" and settings.avatar_profile != "legacy_3d":
                from .avatar_profiles import PROFILES
                profile = PROFILES[settings.avatar_profile]
                # Only the immutable training snapshot changes, never the methodist's source scenario.
                scenario = scenario.model_copy(deep=True, update={"npc_name": profile["title"]})
            session = Session(id=str(uuid4()), participant=request.participant, scenario=scenario, settings=settings,
                              consent=request.consent, voice_consent=request.voice_consent,
                              progress_mode="flexible" if settings.provider == "openai" else "ordered")
            if settings.voice_mode == "avatar" and settings.avatar_profile != "legacy_3d":
                # All consumers already read this saved snapshot: UI, Agent, VoiceTraining and TTS.
                # Failure must leave no partially started session with the unadapted greeting.
                session.scenario.stages[0].opening_line = await self.agent.opening(session, source_name)
            self.store.save_start(request.request_id, session)
            return session

    def save(self, session: Session):
        session.updated_at = now()
        self.store.put("session", session.id, session)

    async def turn(self, sid: str, request: TurnRequest) -> Session:
        async with self.locks[sid]:
            session = self.store.session(sid)
            existing = next((t for t in session.turns if t.request_id == request.request_id), None)
            if existing:
                if existing.user_text != request.text:
                    raise Conflict("Повторный запрос содержит другой текст.")
                return session
            if request.request_id in session.cancelled_requests:
                return session
            if session.status != "active":
                raise Conflict("Тренировка завершена. Можно открыть разбор или начать новую.")
            if any(t.status == "pending" for t in session.turns):
                raise Conflict("Ответ ещё готовится. Остановите его перед новой репликой.")
            if len(session.turns) >= 100:
                raise Conflict("Достигнут предел попыток в этой сессии. Завершите тренировку.")
            turn = Turn(id=str(uuid4()), request_id=request.request_id, user_text=request.text, stage_index=session.stage_index)
            session.turns.append(turn)
            self.save(session)
            task = asyncio.create_task(self.agent.turn(session.model_copy(deep=True)))
            self.tasks[(sid, request.request_id)] = task
        started = perf_counter()
        try:
            decision = await task
        except asyncio.CancelledError:
            return self.store.session(sid)
        except AgentError:
            async with self.locks[sid]:
                session = self.store.session(sid)
                current = next(t for t in session.turns if t.id == turn.id)
                if current.status == "pending":
                    current.status = "failed"
                    self.save(session)
            raise
        finally:
            self.tasks.pop((sid, request.request_id), None)
        async with self.locks[sid]:
            session = self.store.session(sid)
            current = next(t for t in session.turns if t.id == turn.id)
            if current.status != "pending" or session.status != "active":
                return session
            current.reply = decision.reply
            current.elapsed_ms = round((perf_counter() - started) * 1000)
            current.status = "committed"
            current.action = decision.action
            last_stage = session.stage_index == len(session.scenario.stages) - 1
            if session.progress_mode == "flexible":
                previous = session.stage_index
                record_goals(session, getattr(decision, "goals", []))
                complete = len(covered_stages(session)) == len(session.scenario.stages)
                current.action = "advance" if session.stage_index > previous else "stay"
                if decision.action == "finish" and complete:
                    session.status = "completed"
                    session.completion_reason = "scenario_complete"
                    current.action = "finish"
            elif decision.action == "advance" and not last_stage:
                session.stage_index += 1
            elif decision.action == "finish" and last_stage:
                session.status = "completed"
                session.completion_reason = "scenario_complete"
            elif decision.action != "stay":
                current.action = "stay"
            if sum(t.status == "committed" for t in session.turns) >= session.settings.max_turns:
                session.status = "completed"
                session.completion_reason = "turn_limit"
            self.save(session)
            return session

    async def cancel(self, sid: str, request_id: str) -> Session:
        async with self.locks[sid]:
            session = self.store.session(sid)
            if request_id not in session.cancelled_requests:
                session.cancelled_requests.append(request_id)
                session.cancelled_requests = session.cancelled_requests[-100:]
            for turn in session.turns:
                if turn.request_id == request_id and turn.status == "pending":
                    turn.status = "cancelled"
            self.save(session)
            task = self.tasks.get((sid, request_id))
            if task:
                task.cancel()
            return session

    async def end(self, sid: str, *, retry: bool = False) -> Session:
        async with self.locks[sid]:
            session = self.store.session(sid)
            for turn in session.turns:
                if turn.status == "pending":
                    turn.status = "cancelled"
                    task = self.tasks.get((sid, turn.request_id))
                    if task:
                        task.cancel()
            session.status = "completed"
            session.completion_reason = session.completion_reason or "user_finished"
            if session.report_status in {"pending", "ready"} or (session.report_status == "failed" and not retry):
                self.save(session)
                return session
            session.report_status = "pending"
            session.report_error = ""
            self.save(session)
        try:
            report = await self.agent.assess(session)
        except AgentError as exc:
            async with self.locks[sid]:
                session = self.store.session(sid)
                session.report_status = "failed"
                session.report_error = str(exc)
                self.save(session)
                return session
        async with self.locks[sid]:
            session = self.store.session(sid)
            session.report = report
            session.report_status = "ready"
            self.save(session)
            return session


def scenario_view(scenario, staff=False, enrich=True):
    if enrich:
        from .seeds import with_public_situation
        scenario = with_public_situation(scenario)
    value = scenario.model_dump()
    if not staff:
        for key in ("context", "boundaries", "manner"):
            value.pop(key, None)
        value["stages"] = [{"id": s.id, "title": s.title, "objective": s.objective} for s in scenario.stages]
    return value


def session_view(session: Session, staff=False):
    value = session.model_dump(exclude={"settings", "cancelled_requests", "consent", "voice_consent"})
    value["scenario"] = scenario_view(session.scenario, staff, enrich=False)
    value["mode"] = session.settings.mode
    value["is_demo"] = session.settings.provider == "demo"
    value["max_turns"] = session.settings.max_turns
    value["voice_mode"] = session.settings.voice_mode
    value["avatar_profile"] = session.settings.avatar_profile
    value["allow_audio_fallback"] = session.settings.allow_audio_fallback
    value["opening_message"] = session.scenario.stages[0].opening_line
    if staff:
        value["settings"] = session.settings.model_dump()
    return value
