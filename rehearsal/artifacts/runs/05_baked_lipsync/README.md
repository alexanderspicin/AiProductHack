# Локальная лаборатория липсинка

[Выводы и простой план](notes.md) · [Источники](sources.md) · [Журнал](runlog.md)

Открыть [http://127.0.0.1:8896](http://127.0.0.1:8896). Выбрать фразу, нажать «Произнести», затем сравнить три режима. Можно ввести свой текст и прервать ответ. Микрофон не используется. Основное приложение на 5175 не затронуто.

## Повторный запуск на этом Mac

Из корня `rehearsal`:

```sh
.venv/bin/python artifacts/runs/05_baked_lipsync/lab.py serve
```

Локальные материалы уже лежат в `artifacts/private/05_baked_lipsync`, эта папка исключена из Git. Python читает только их. Сервер слушает исключительно 127.0.0.1. Если порт занят запущенной лабораторией, второй экземпляр не нужен.

## Воспроизведение на другом Mac

Требуются Python 3.12, `numpy`, `onnxruntime`, `Pillow`, `huggingface_hub`, FFmpeg и русский голос Milena (`say -v '?'`). Модели и демоматериалы сначала скачиваются из интернета. Сам эксперимент после загрузки не обращается к API.

Из корня проекта подготовить отдельное окружение, чтобы не менять зависимости Pipecat:

```sh
python3.12 -m venv artifacts/private/lipsync-venv
artifacts/private/lipsync-venv/bin/pip install numpy==2.5.2 onnxruntime==1.24.4 Pillow==12.3.0 huggingface_hub
mkdir -p artifacts/private/05_baked_lipsync/vendor
git clone https://github.com/ryanhuge/emma-skin artifacts/private/05_baked_lipsync/emma-source
git -C artifacts/private/05_baked_lipsync/emma-source checkout 4e20e3d
git clone https://github.com/kleinlee/DH_live artifacts/private/05_baked_lipsync/dh-source
git -C artifacts/private/05_baked_lipsync/dh-source checkout 4467e97
cp -R artifacts/private/05_baked_lipsync/emma-source/assets/emma artifacts/private/05_baked_lipsync/vendor/emma
cp -R artifacts/private/05_baked_lipsync/dh-source/web_demo/static artifacts/private/05_baked_lipsync/vendor/dh
cp artifacts/private/05_baked_lipsync/emma-source/NOTICE artifacts/private/05_baked_lipsync/vendor/EMMA_NOTICE
cp artifacts/private/05_baked_lipsync/emma-source/LICENSE artifacts/private/05_baked_lipsync/vendor/EMMA_LICENSE
artifacts/private/lipsync-venv/bin/hf download myned-ai/wav2arkit_cpu wav2arkit_cpu.onnx wav2arkit_cpu.onnx.data config.json README.md --local-dir artifacts/private/05_baked_lipsync/model
artifacts/private/lipsync-venv/bin/python artifacts/runs/05_baked_lipsync/lab.py prepare
artifacts/private/lipsync-venv/bin/python artifacts/runs/05_baked_lipsync/lab.py serve
```

Клонирование и копирование выше рассчитаны на новую папку. Не запускать повторно поверх готовой структуры. Веса модели берутся из публичного репозитория; его автор может обновить экспорт. Это не обещание неизменности удалённых файлов. Скрипт проверяет размерность и конечность результата, байтовые сравнения не используются.

Для Linux нужно заменить только локальный синтез `say` в `synthesize()` на доступный TTS с выходом WAV mono PCM16, 16 kHz. Такая замена здесь не проверялась.

## Проверки и видеопримеры

```sh
.venv/bin/python artifacts/runs/05_baked_lipsync/lab.py prepare
.venv/bin/python artifacts/runs/05_baked_lipsync/render_cpu.py
.venv/bin/python -m unittest discover -v -s artifacts/runs/05_baked_lipsync -p test_lab.py
```

`prepare` повторно синтезирует фиксированные фразы и перезаписывает только материалы эксперимента и его метрики. Не запускать одновременно с человеческой оценкой, чтобы не смешивать версии аудио.

Для браузерной проверки требуется установленный Playwright с Chromium. Передать его путь через `LIPSYNC_PLAYWRIGHT`, если пакет не находится стандартным поиском Node, и выполнить:

```sh
node artifacts/runs/05_baked_lipsync/browser_probe.mjs
```

Проверка использует тестовую страницу на 8896, не тренажёр. Playwright запускает Chromium с Metal, поэтому её результаты не обозначены CPU-only. Она проверяет все три режима, новое высказывание, отмену и мобильную ширину. Нужна отдельная человеческая проверка звука и артикуляции.

После `render_cpu.py` доступны:

- [Рот по громкости, CPU-видео](http://127.0.0.1:8896/data/cpu_energy.mp4).
- [Аудиомодель и готовые формы, CPU-видео](http://127.0.0.1:8896/data/cpu_model.mp4).
- `artifacts/private/05_baked_lipsync/cpu_contact_sheet.jpg`, кадры для визуальной проверки.
- `lab_desktop.png`, `lab_mobile.png`, `lab_neural.png`, снимки браузера.

## Ограничения и права

Фрагменты формул выбора и наложения изображений адаптированы из EMMA Skin, Ryan Chen, Apache-2.0. Их влияние явно указано в исходниках. Сохранены LICENSE и NOTICE поставщика.

DH Live загружается локально из исходного демопакета. Логотип MatesX не удаляется. README автора отдельно описывает авторизацию аватаров, поэтому его демолицо не включено в публичный проект и не объявлено свободным для нашего коммерческого выпуска.

Здесь нет ключей, облачного TTS, ASR или интеграции нового аватара в Pipecat. Внешние расходы эксперимента 0 ₽. Локальные файлы модели и роликов не должны попадать в обычный Git-коммит.
