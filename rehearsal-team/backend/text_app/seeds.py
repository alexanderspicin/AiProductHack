import json
from pathlib import Path

from .models import Criterion, Scenario, Stage
from .store import Store


def builtin_scenarios():
    source = json.loads((Path(__file__).parent / "scenarios/sales_objection.json").read_text())
    sales = Scenario(
        id="sales-objection", title=source["title"], category="Продажи",
        description=source["description"], employee_role=source["employee_role"],
        situation="Вы встречаетесь с представителем компании, чтобы обсудить корпоративное обучение. Решение о покупке ещё не принято. Собеседник ждёт конкретного предложения и не готов тратить время на общие обещания.",
        npc_name=source["npc"]["name"], npc_role=source["npc"]["role"],
        manner=source["npc"]["manner"], context=source["npc"]["hidden_context"],
        boundaries=source["npc"]["unknown_context"], status="published",
        stages=[Stage(**{k: v for k, v in s.items() if k != "allowed_actions"}) for s in source["stages"]],
        criteria=[Criterion(**{**c, "weight": 2 if c["weight"] >= 1.3 else 1}) for c in source["rubric"]],
    )
    feedback = Scenario(
        id="feedback", title="Обратная связь без конфликта", category="Управление",
        description="Обсудите с коллегой сорванный срок. Выясните причину и договоритесь о следующих шагах, сохранив рабочие отношения.",
        situation="Второй раз отчёт от специалиста вашей команды поступил позже согласованного срока. Вы пригласили коллегу на разговор об этой ситуации. Причину задержки вам предстоит выяснить.",
        employee_role="Руководитель команды", npc_name="Михаил Соколов", npc_role="Специалист вашей команды",
        manner="Защищаешься, если тебя обвиняют. Готов обсуждать факты и принимать конкретную помощь.",
        context="Дважды задержал отчёт. Одновременно поступили срочные задачи от другого руководителя. Сам не предупредил о риске и понимает это. Расскажи о параллельных задачах, когда руководитель спросит о причинах.",
        boundaries="Не выдумывай фамилии, даты и дисциплинарные взыскания. Не соглашайся с расплывчатыми требованиями.",
        status="published", duration_minutes=6,
        stages=[
            Stage(id="facts", title="Обсудить факты", objective="Назвать наблюдаемое поведение и его последствия без обвинений.", opening_line="Вы хотели обсудить отчёт? Я его уже отправил. Не понимаю, почему мы опять к этому возвращаемся."),
            Stage(id="cause", title="Понять причину", objective="Выслушать объяснение и уточнить, что мешало выполнить задачу.", opening_line="У меня были ещё срочные задачи. Я не мог сделать всё одновременно."),
            Stage(id="agreement", title="Договориться", objective="Определить действие, срок и способ предупреждения о риске.", opening_line="Хорошо, что мне делать, если приоритеты снова столкнутся?"),
        ],
        criteria=[
            Criterion(id="facts", title="Конкретная обратная связь", description="Описывает факты и последствия, избегает оценок личности."),
            Criterion(id="listen", title="Выяснение причин", description="Задаёт открытые вопросы и учитывает объяснение сотрудника.", weight=2),
            Criterion(id="agreement", title="Рабочая договорённость", description="Фиксирует действие и точку проверки результата.", weight=2),
        ],
    )
    support = Scenario(
        id="support", title="Клиент ждёт решения", category="Поддержка",
        description="Помогите клиенту, который не получил ответ вовремя. Снизьте напряжение, уточните ситуацию и предложите понятный следующий шаг.",
        situation="Клиент повторно обращается в поддержку: со вчерашнего дня не получается войти в личный кабинет, а предыдущее обращение осталось без ответа. Вы принимаете этот разговор и можете уточнить проблему и организовать следующий шаг.",
        employee_role="Специалист клиентской поддержки", npc_name="Елена Миронова", npc_role="Клиент сервиса",
        manner="Расстроена задержкой. На сочувствие и конкретные действия реагируешь спокойно, на отговорки раздражаешься.",
        context="Не можешь войти в личный кабинет. Уже писала в поддержку вчера и не получила ответа. Ошибка возникает после ввода пароля. Других подробностей пока нет.",
        boundaries="Не сообщай реальный пароль и персональные данные. Не выдумывай техническую причину сбоя и гарантированный срок исправления.",
        duration_minutes=5, status="published",
        stages=[
            Stage(id="contact", title="Снять напряжение", objective="Признать неудобство и показать готовность помочь.", opening_line="Я со вчерашнего дня не могу войти в кабинет. Мне вообще кто-нибудь поможет?"),
            Stage(id="clarify", title="Уточнить ситуацию", objective="Собрать необходимые детали ошибки, не запрашивая пароль.", opening_line="После ввода пароля появляется ошибка. Что вам ещё нужно узнать?"),
            Stage(id="solution", title="Предложить решение", objective="Объяснить безопасный следующий шаг или передачу специалисту и срок обратной связи.", opening_line="Хорошо. Что мне делать сейчас и когда ждать ответа?"),
        ],
        criteria=[
            Criterion(id="empathy", title="Внимание к клиенту", description="Признаёт неудобство и отвечает на эмоцию клиента."),
            Criterion(id="details", title="Уточняющие вопросы", description="Собирает полезные сведения, не просит пароли или лишние персональные данные."),
            Criterion(id="solution", title="Следующий шаг", description="Даёт понятную инструкцию или план передачи вопроса специалисту.", weight=2),
        ],
    )
    return support, feedback, sales


def with_public_situation(scenario: Scenario) -> Scenario:
    """Enrich an unchanged bundled template, not an edited scenario or saved session."""
    if scenario.situation:
        return scenario
    excluded = {"revision", "updated_at", "situation", "npc_name"}
    for template in builtin_scenarios():
        if scenario.id == template.id and scenario.model_dump(exclude=excluded) == template.model_dump(exclude=excluded):
            return scenario.model_copy(deep=True, update={"situation": template.situation})
    return scenario


def seed(store: Store):
    if store.all("scenario"):
        return
    for scenario in builtin_scenarios():
        store.put("scenario", scenario.id, scenario)
