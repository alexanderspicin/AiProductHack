# Голос и реалистичный аватар: выбор для Pipecat

Дата: 2026-09-05. Режим TASK2_AI, исследование без изменения приложения. Дедлайн не задан. Платных запросов: 0. Проверка документации, не сравнительное прослушивание и не измерение задержки.

Критерии: русский диалог, потоковый ввод и вывод, отмена, сохранение серверных Silero/Smart Turn и тренировочного агента, реалистичный человек вместо стилизованного GLB. Порядок ниже означает приоритет экспериментов, не доказанный рейтинг качества.

Поиск выполнен несколькими сериями: ElevenLabs Flash/v3 Russian; Cartesia Sonic current models; Inworld TTS timestamps; Hume Octave Russian/streaming; Fish current models; Yandex SpeechKit; Simli migration/interrupt; LiveAvatar LITE; Tavus Echo; Anam audio passthrough/Pipecat; D-ID realtime/Expressive. Старые поисковые фрагменты сверены с текущими страницами: Sonic теперь 3.6, Fish рекомендует S2.1-Pro, Simli изменил endpoints. Markdown LiveAvatar не открылся в web; HTML Events доступен. Непроверенные цены и рекламные рейтинги не используются.

## Голос: пять кандидатов

1. ElevenLabs v3 Conversational / Flash v2.5. Выразительность против минимальной задержки; русский поддерживается. Flash требует внимания к числам. https://elevenlabs.io/docs/overview/models
2. Cartesia Sonic 3.6. Русский, потоковый WebSocket, отмена контекста, timestamps. Зафиксировать snapshot для воспроизводимого теста. https://docs.cartesia.ai/build-with-cartesia/tts-models/latest и https://docs.cartesia.ai/api-reference/tts/websocket
3. Inworld TTS-2 / 1.5 Max. Уже выбран командой; проверить до замены. Текущая документация описывает фонемы и visemeSymbol с WORD alignment; async alignment может приходить после звука. https://docs.inworld.ai/tts/tts и https://docs.inworld.ai/tts/capabilities/timestamps
4. Fish Audio S2.1-Pro. Управление подачей, потоковый API. Есть s2.1-pro-free с fair-use и без гарантии TTFA/DPA: годится для синтетической проверки, не для обещания задержки. https://docs.fish.audio/developer-guide/models-pricing/models-overview и https://docs.fish.audio/developer-guide/models-pricing/choosing-a-model
5. Hume Octave 2. Русский, эмоциональные инструкции, WebSocket и фонемные метки; документация обозначает preview. https://dev.hume.ai/docs/text-to-speech-tts/overview и https://dev.hume.ai/reference/text-to-speech-tts/stream-input

Резерв: SpeechKit имеет потоковый API v3; Brand Voice Lite не поддерживает потоковый синтез. Не ставим проект обучения брендового голоса перед ближайшим демо. https://yandex.cloud/ru-kz/docs/speechkit/tts/

## Реалистичный видеоперсонаж: пять кандидатов

1. Anam Cara-4 + pipecat-anam. enable_audio_passthrough=True сохраняет наш TTS/агента; сервис возвращает согласованные аудио и видео, обрабатывает InterruptionFrame. https://github.com/anam-org/pipecat-anam и https://anam.ai/blog/pipecat-frame-processing-guide
2. HeyGen LiveAvatar LITE. Видеослой отдельно от собственного ASR/LLM/TTS; не выбирать FULL, если сохраняем архитектуру команды. https://docs.liveavatar.com/ и https://docs.liveavatar.com/docs/lite-mode/events
3. Tavus CVI Echo. Audio Echo отключает собственные Perception/STT/LLM/TTS; прерывания нужно увязать с нашим контроллером. Сам Tavus предпочитает полный пайплайн для максимальной оптимизации: качество/задержку Echo проверять отдельно. https://docs.tavus.io/sections/conversational-video-interface/echo-mode
4. Simli Compose. Поток аудио, WebRTC, ClearBuffer. Предыдущее наблюдение рассинхронизации не доказывает отсутствие русского: проверить формат, воспроизведение возвращённого звука и отмену. https://docs.simli.com/api-reference/javascript и https://docs.simli.com/api-reference/api_migration_guide
5. D-ID Expressive V4 / Realtime. Новая ветка SDK, прерывания; компоненты STT/LLM/TTS необязательны в realtime API. Не начинать с legacy Talks. https://docs.d-id.com/docs/realtime-overview и https://docs.d-id.com/reference/agents-sdk-overview

## Вывод и следующий эксперимент

Не заменять Pipecat. Первая практическая связка: существующий Inworld + Anam audio passthrough. Сравнение голоса: тот же персонаж и текст, ElevenLabs против Inworld. Второй видеокандидат: LiveAvatar LITE. Изменение транспорта для видеопотока допустимо, изменение логики тренировок не требуется.

Сначала слепая оценка одинаковых 8–10 коротких русских фраз: нейтрально, сомнение, недовольство, сочувствие, числа, имена, смешанный текст. Затем один сохранённый PCM подать каждому видеокандидату. Оценить губы, зубы, взгляд, голову, состояние слушания и остановку. Два финалиста проверить живым диалогом. Права на лицо и голос обязательны. Для avatar API воспроизводить возвращённый синхронизированный звук, не параллельный исходный TTS.

Нет победителя по фактическому качеству русского без человеческого сравнения. Рекламные задержки моделей не равны времени от конца реплики до первого слышимого ответа. Финальный выбор и платный тест требуют согласования доступа/стоимости.
