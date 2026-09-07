# API тренажёра

Дополнение 6 сентября: [контракт двух живых персонажей](docs/SELECTED_AVATARS.md). Методист использует PUT `/api/text/presentation`. Для выбранных профилей prepare требует `request_id` и принимает `audio_only`; в ответе возвращает краткоживущий путь WebSocket с lease и токен выбранного видеосервиса. Мастер-ключей в ответе нет. Stop принимает тот же `request_id`. Контракт визем ниже относится к прежнему `legacy_3d`.
Сервер по умолчанию слушает `127.0.0.1:8001`, Vite проксирует HTTP и WebSocket через `/api/text`. Схемы REST доступны на `/docs`.

| Действие | Запрос |
| --- | --- |
| Сценарии, история, настройки | GET /api/text/bootstrap?role=participant или methodist или admin |
| Создание и изменение сценария | POST /api/text/scenarios, PUT /api/text/scenarios/{id} |
| Настройки администратора | PUT /api/text/settings |
| Создание тренировки | POST /api/text/sessions |
| Состояние и стенограмма | GET /api/text/sessions/{id} |
| Текстовая реплика | POST /api/text/sessions/{id}/turns |
| Отмена текстового ответа | POST /api/text/sessions/{id}/cancel |
| Завершение и отчёт | POST /api/text/sessions/{id}/end |
| Повтор отчёта | POST /api/text/sessions/{id}/report |
| Комментарий методиста | PUT /api/text/sessions/{id}/review |
| Готовность голосового сервера | GET /api/text/pipeline/status |
| Проверка сессии перед голосом | POST /api/text/sessions/{id}/voice/prepare |
| Голосовой транспорт | WS /api/text/sessions/{id}/voice/ws |
| Остановка с сохранением стенограммы | POST /api/text/sessions/{id}/voice/stop |

Для старта нужны `scenario_id`, `request_id`, `participant`, `consent` для OpenAI и `voice_consent` для выбранных сервисов голоса и видео. Настройки фиксируются в сессии. Изменение сценария и настроек требует актуальную `revision`.

Голосовой контракт полностью Pipecat: ProtobufFrameSerializer, официальный WebSocketTransport, RTVI и события аватара из `backend/app/avatar/protocol.py`. Отдельных WAV-запросов, REST-синтеза и фронтенд-VAD нет.

События визем и субтитров содержат `utterance_id` и `audio_offset_ms`. Браузер планирует их относительно фактического старта PCM на AudioContext. Прерывание очищает аудиобуферы и очередь событий. Текст во время голоса отправляется официальным `sendText` с `run_immediately=true, audio_response=true`, а не REST-запросом `/turns`.

`voice/prepare` возвращает относительный `path`. Клиент создаёт ws/wss URL из текущего origin. После разрешения микрофона Pipecat отправляет PCM-поток и воспроизводит возвращённый звук.

Серверная Silero VAD инициирует встроенное прерывание Pipecat до распознавания текста. Smart Turn определяет окончание пользовательского хода. STT и TTS сохраняют исходные настройки команды.

Текст реплик сохраняется по событиям агрегаторов Pipecat. Поле `interrupted=true` отмечает прерванного собеседника. Реплика участника остаётся в оценке; неозвученная часть ответа не подставляется из полного LLM-результата.

Для отчёта сначала остановите голос и дождитесь `voice/stop`. Одна сессия допускает одно голосовое подключение. REST-реплики и завершение при активном голосе возвращают 409.

Роли демонстрационные, не авторизация. WebSocket принимает только локальный browser origin.
