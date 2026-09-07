"""Training state adapter. Audio, turn detection and interruption belong to Pipecat."""
import json
from uuid import uuid4

from .models import GoalObservation, Turn
from .progress import progress_context, record_goals
from .roleplay import FLEXIBLE_RULES, role_instruction
from .store import Conflict


class VoiceTraining:
    def __init__(self, service, sid):
        self.service, self.sid = service, sid
        self.current_turn = None
        self.seen_tools = set()
        self.worker = None

    @property
    def session(self):
        return self.service.store.session(self.sid)

    def instruction(self):
        s = self.session
        if s.progress_mode == "flexible":
            return role_instruction(s) + FLEXIBLE_RULES + (
                "Когда новая цель подтверждена, вызови advance_stage с её stage_id и короткой дословной evidence участника. "
                "Можно отметить любую цель независимо от current_stage, несколько целей отдельными вызовами. "
                "Уже отмеченные повторно не вызывай. Инструмент сохраняет наблюдение и обновляет внутренний этап; "
                "его результат не произноси. Не начинай ответ с объяснения того, что ты проверяешь. "
                "Если все цели обсуждены, можно естественно закончить разговор, без оценки и инструкции нажимать кнопки.\n"
            ) + json.dumps(progress_context(s), ensure_ascii=False)
        return role_instruction(s) + (
            "\nСлужебный учёт этапов, не произноси его вслух. Когда цель этапа достигнута, "
            "вызови advance_stage с текущим stage_id и дословной цитатой участника. "
            "Инструмент вернёт следующий этап, но это не команда сменить тему: сначала ответь по существу. "
            "Не называй балл: разбор выполняется отдельно по стенограмме.\n" +
            json.dumps({"stages": [stage.model_dump(exclude={"opening_line"}) for stage in s.scenario.stages], "current_stage": s.scenario.stages[s.stage_index].id}, ensure_ascii=False)
        )

    def history(self):
        messages = [{"role": "assistant", "content": self.session.scenario.stages[0].opening_line}]
        for t in self.session.turns:
            if t.status == "committed":
                messages.append({"role": "user", "content": t.user_text})
                if t.reply:
                    messages.append({"role": "assistant", "content": t.reply})
        return messages

    async def user_message(self, text):
        if not text or not text.strip():
            return
        async with self.service.locks[self.sid]:
            s = self.session
            if s.status != "active":
                return
            if len(s.turns) >= s.settings.max_turns:
                return
            self.current_turn = str(uuid4())
            s.turns.append(Turn(id=self.current_turn, request_id=self.current_turn, user_text=text.strip(),
                                stage_index=s.stage_index, status="committed"))
            self.service.save(s)

    async def assistant_message(self, text, interrupted=False):
        async with self.service.locks[self.sid]:
            s = self.session
            turn = next((t for t in s.turns if t.id == self.current_turn), None)
            if turn:
                turn.reply = text or ""
                turn.interrupted = interrupted
                self.service.save(s)
            self.current_turn = None
            if len(s.turns) >= s.settings.max_turns and self.worker:
                from pipecat.frames.frames import EndFrame
                s.status = "completed"
                s.completion_reason = "turn_limit"
                self.service.save(s)
                await self.worker.queue_frame(EndFrame())

    async def advance(self, stage_id, evidence, call_id):
        async with self.service.locks[self.sid]:
            s = self.session
            stage = s.scenario.stages[s.stage_index]
            if s.progress_mode == "flexible":
                def result(advanced=False):
                    return {"stage": s.scenario.stages[s.stage_index].model_dump(exclude={"opening_line"}),
                            "advanced": advanced, **progress_context(s), "instruction": "Продолжай от лица персонажа, ответь на последнюю реплику. Не озвучивай учёт целей."}
                if call_id in self.seen_tools:
                    return result()
                if not isinstance(stage_id, str) or not 1 <= len(stage_id.strip()) <= 80 or not isinstance(evidence, str) or not 3 <= len(evidence.strip()) <= 500:
                    return {"error": "Нужны stage_id и короткая дословная цитата участника."}
                previous = s.stage_index
                accepted = record_goals(s, [GoalObservation(stage_id=stage_id, quote=evidence)])
                if not accepted:
                    return {**result(), "error": "Цель уже отмечена, неизвестна или не подтверждена репликой участника."}
                self.seen_tools.add(call_id)
                self.service.save(s)
                return result(s.stage_index > previous)
            if call_id in self.seen_tools or stage.id != stage_id:
                return {"stage": stage.model_dump(exclude={'opening_line'}), "advanced": False}
            if s.status != "active" or not isinstance(evidence, str) or not evidence.strip() or not any(
                evidence in t.user_text for t in s.turns if t.status == "committed" and t.stage_index == s.stage_index
            ):
                return {"error": "Нужна дословная цитата участника из текущего этапа."}
            self.seen_tools.add(call_id)
            if s.stage_index < len(s.scenario.stages) - 1:
                s.stage_index += 1
                self.service.save(s)
                return {"stage": s.scenario.stages[s.stage_index].model_dump(exclude={'opening_line'}), "advanced": True}
            return {"stage": stage.model_dump(exclude={'opening_line'}), "advanced": False, "instruction": "Цель последнего этапа достигнута. Подведи итог."}


def validate_voice_session(session):
    if session.status != "active" or session.settings.voice_mode != "avatar":
        raise Conflict("Откройте активную тренировку в голосовом режиме.")
    if session.settings.provider != "openai":
        raise Conflict("Для голосовой тренировки администратор должен выбрать OpenAI.")
    if not session.consent or not session.voice_consent:
        raise Conflict("Для разговора нужны согласия на OpenAI и выбранные сервисы голоса и видео.")
