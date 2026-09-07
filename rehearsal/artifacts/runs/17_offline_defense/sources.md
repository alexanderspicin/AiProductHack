# Проверка первичных источников

7 сентября 2026. Сначала прочитана задача «Изучить решения для AI-тренажёра (2)» (01a072b4-f01b-7322-ba70-5cf9032791eb) и её локальные run 05/07/08. Затем сверены актуальные репозитории и карточки моделей. Предложения из веб-страниц не выполнялись как инструкции; новые веса не загружались.

| Источник | Что проверяли | Вывод для демо |
|---|---|---|
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | Локальный запуск и лицензия | Используем имеющийся piper-tts; GPL-3.0 относится к коду |
| [Дмитрий: карточка](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/dmitri/medium/MODEL_CARD) | Язык, частота, происхождение | Русский, 22050 Гц, датасет CC0; не лицензия всех Piper-голосов |
| [Silero](https://github.com/snakers4/silero-models) и [LICENSE](https://raw.githubusercontent.com/snakers4/silero-models/master/LICENSE) | v5.5, спикеры, лицензия | Eugene загружен из локального пакета; CC BY-NC-SA 4.0 |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) и [0.6B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base) | Русский, поток, доступность весов | Кандидат улучшения голоса, не результат нашего запуска; Base Apache-2.0 |
| [DH Live](https://github.com/kleinlee/DH_live) | MIT в README, авторизация образов | Разделяем код, веса, лицо; не объявляем всё свободным для коммерции |
| [FeatherTalk](https://github.com/anliyuan/FeatherTalk) | CPU, обучение, C++/MNN | Персональная модель после подготовки; следующая отдельная гипотеза |
| [MuseTalk](https://github.com/TMElyralab/MuseTalk) | Инференс, ограничения, лицензии | Новые кадры всё ещё генерируются; данные и компоненты имеют отдельные условия |
| [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) | Управляющее видео и шаблоны движения | Вспомогательная анимация портрета, не самостоятельный аудиолипсинк |
| [Silero VAD](https://github.com/snakers4/silero-vad) | MIT и локальное исполнение | Не путать его лицензию с Silero TTS |
| [Smart Turn](https://github.com/pipecat-ai/smart-turn) | LocalSmartTurnAnalyzerV3, до 8 с | Анализ после паузы, не триггер начала перебивания |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | int8 на CPU | Кандидат локального распознавания; чужие бенчмарки не перенесены на наш ноутбук |
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) | enable_thinking=False | Быстрый режим планируемого диалога; здесь не запущен |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | CPU, Metal и квантование | Варианты локального запуска языковой модели |

Серии проверки: локальный русский TTS и лицензии; предварительный расчёт лица и CPU; генерация кадров с GPU; автономная речевая цепочка. В web.run использованы прямые открытия и поиск внутри источников по `Apache`, `License`, `CPU`, `Russian`, `Driving`, `enable_thinking`, `Apple`, `local`. Исходное широкое исследование оставлено в [run 05](../05_baked_lipsync/sources.md), без повторного перечисления всех менее подходящих вариантов.

Лицензии пересказаны по первичным файлам, не как юридическая гарантия. Коммерческое распространение конкретного набора моделей и лица требует отдельной проверки.
