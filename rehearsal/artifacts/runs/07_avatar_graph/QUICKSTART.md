# Сборка и запуск

Обновлено 6 сентября 2026. Команды из корня `rehearsal`. Основной Pipecat-проект не меняется. Токены API не нужны. Все модели и медиаданные держим в исключённой из Git папке `artifacts/private/`.

Проверено: новый пакет 4 позы × 8 состояний из сохранённых исходников, весов и WAV, затем офлайн-расчёт на CPU, импорт и новая фраза. Полный пакет 100 × 64 ранее рассчитан на H100. Путь с новой фотографией ещё не проверен. Это воспроизводимость алгоритма, не обещание побитового совпадения между версиями TTS, PyTorch и разным железом.

## 1. Просто запустить готового человека

```sh
artifacts/private/07_avatar_graph/cpu_env/bin/python artifacts/runs/07_avatar_graph/workflow.py serve --root artifacts/private/07_avatar_graph --port 8897
```

Открыть http://127.0.0.1:8897. Если порт занят работающей лабораторией, второй сервер не запускать. Текст требует macOS с Milena и ffmpeg. Сервер запускать из обычного терминала: песочница может запретить macOS синтезировать звук. Тихий результат теперь отклоняется с объяснением.

Для другого TTS открыть «Проверить другой голос из WAV»: PCM16, моно/стерео, до 45 с и 10 МБ. Сервер переводит звук в 16 кГц mono; нейросетевая обработка изображений не запускается. До воспроизведения готовится весь WAV, потоковый TTS ещё не подключён.

## 2. Подготовить окружение для новой сборки

Не устанавливать тяжёлые зависимости в окружение работающего тренажёра. Нужны Python 3.12, Node, git и ffmpeg. Версии ниже соответствуют локальной проверке на M3 Pro; для CUDA нужна отдельная совместимая сборка PyTorch.

```sh
uv venv artifacts/private/avatar-build-env --python 3.12
uv pip install --python artifacts/private/avatar-build-env/bin/python -r artifacts/runs/07_avatar_graph/requirements-cpu.txt torch==2.14.0 onnx==1.22.0 opencv-python-headless==5.0.0.93 huggingface_hub
npm install --prefix artifacts/private/avatar-build-js @playwright/test
artifacts/private/avatar-build-js/node_modules/.bin/playwright install chromium
```

Playwright здесь только растеризует геометрию через WebGL при подготовке. Это не нейросетевая генерация лица. На Mac используется Metal; на других системах указан SwiftShader. Офлайн-растеризация должна запускаться вне ограниченной песочницы. Полностью новые установки всех пакетов в этом повторном прогоне не выполнялись: проверялось существующее изолированное окружение.

## 3. Получить исходники и веса

Автоматическая загрузка из публичных источников, без ключей:

```sh
artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py fetch --root artifacts/private/my-avatar
```

Скрипт закрепляет DH Live на commit `4a90da6e32b9cef7ed850455eddc754abed8b454`. Нужны именно старые веса `epoch_40.pth` и `lstm_model_epoch_325.pkl`. Текущая mini2.0 не подставляется вместо них. Если `fetch` прервался после скачивания исходников, не повторять его в непустую папку: завершить указанную в журнале загрузку или выбрать новую папку. Этот повторный прогон не проверял скачивание с нуля.

На текущем компьютере можно обойтись без повторного скачивания. Вместо `fetch`:

```sh
.venv/bin/python artifacts/runs/07_avatar_graph/workflow.py init-local --root artifacts/private/my-avatar --from-root artifacts/private/07_avatar_graph
```

Оба варианта создают `teacher_source/` и `teacher_weights/`. Они альтернативны: выбрать один, не запускать последовательно в одной папке.

## 4. Подготовить данные

Для текущего демолика:

```sh
LIPSYNC_PLAYWRIGHT="$PWD/artifacts/private/avatar-build-js/node_modules/@playwright/test" artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py prepare --root artifacts/private/my-avatar --poses 100 --states 64
```

По умолчанию используются демопакет DH Live и macOS `say`. Для повторения по уже сохранённому звуку добавить:

```text
--audio-dir artifacts/private/07_avatar_graph/inputs
```

Папка должна содержать `calibration_0.wav` ... `calibration_7.wav`, `new_training.wav`, `new_closures.wav`, `new_rounding.wav`. Это PCM16 mono. Тексты есть в `prepare.py`. Калибровка и три проверочные фразы разделены; не подменять отложенные фразы калибровкой.

Для другого **уже подготовленного DH Live mini v1 пакета** добавить `--assets PATH_TO_ASSETS`. Внутри нужны `01.mp4` и `combined_data.json.gz`, `ref_data` из 6480 чисел. Не передавать туда просто JPG. Для быстрой проверки поставить `--poses 4 --states 8`; это проверка сборки, не рекомендуемое качество.

Результат:

```text
my-avatar/
  inputs/              WAV, управляющие параметры, геометрические карты
  package/base/        обычные кадры человека
  package/manifest.json  позы, состояния, масштаб, параметры выбора, build_id
  package/audio_driver.onnx  маленькая модель «звук в движения»
  commands.jsonl       команды, время и код завершения
```

## 5. Один раз рассчитать изображения

Если CUDA-машина уже содержит весь `my-avatar/`:

```sh
python artifacts/runs/07_avatar_graph/workflow.py bake --root artifacts/private/my-avatar
```

Для GPU без интернета сначала подготовить переносимую папку:

```sh
.venv/bin/python artifacts/runs/07_avatar_graph/workflow.py export-gpu --root artifacts/private/my-avatar --out artifacts/private/my-avatar-job
```

Перенести `my-avatar-job/` на свою согласованную GPU-машину. Внутри есть `RUN.txt` и `bake_gpu.py`; выполнить `python bake_gpu.py --root .`. Нужны NumPy, Pillow, CUDA PyTorch и opencv-python-headless. Все входы и веса уже включены, внешняя сеть во время расчёта не нужна. Скрипт сам не создаёт pod и не меняет число реплик. Вернуть папку `baked/`.

Без GPU доступна проверенная альтернатива для маленькой сборки:

```sh
artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py bake --root artifacts/private/my-avatar --device cpu
```

Это **предварительная** генерация кадров нейросетью на CPU, не режим разговора. В повторном тесте рассчитаны 32 элемента библиотеки и 474 контрольных кадра. Этот маленький замер нельзя переносить на большую библиотеку без проверки.

## 6. Подключить библиотеку и произнести новую фразу

```sh
artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py import-baked --root artifacts/private/my-avatar --input artifacts/private/my-avatar/baked
artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py serve --root artifacts/private/my-avatar --port 8898
```

Импорт проверяет `build_id` и декодирует все атласы. Другую сборку не смешивает с этой. `--legacy` нужен только для старого пакета run07 без нового служебного файла.

Онлайн остаются только небольшой аудиодрайвер, выбор готовых состояний и Canvas. Пользователь может менять текст сколько угодно. Изображения не пересчитываются. Рот идёт по звуку, голова отдельно: спокойный темп, плавные развороты, малое дыхание корпуса. В основной проверке интерфейс показал около 30 кадров/с.

Контрольный MP4 с прежним движением головы, **без новых эффектов поведения**:

```sh
artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py infer --root artifacts/private/my-avatar --input new_phrase.wav --out new_phrase.mp4
```

## 7. Перенести без окружения подготовки

```sh
artifacts/private/avatar-build-env/bin/python artifacts/runs/07_avatar_graph/workflow.py pack --root artifacts/private/my-avatar --out artifacts/private/my-avatar.tar.gz
```

Архив включает картинки, аудиодрайвер, интерфейс и CPU-скрипты. Нет весов генерации изображений, ключей или введённых пользователем фраз. Готовые примеры включаются, если существуют. Распаковать в новую папку и следовать `package/README.md`. У коллег потребуется установить только CPU-зависимости и ffmpeg. Для новой фотографии или коммерческого использования сначала проверить права на внешность, исходное видео и веса.

## Новый человек из видео или фотографии

Это отдельный пока не пройденный для новой внешности этап. Для закреплённой старой версии DH Live исходники содержат команды:

```sh
python data_preparation_mini.py consented_video.mp4 prepared_person
python data_preparation_web.py prepared_person
```

Они создают `prepared_person/assets`. Требуют окружения исходного DH Live, MediaPipe старого интерфейса, его вспомогательных файлов и весов. Не смешивать это окружение с нашим CPU-проигрывателем. Новый пакет затем передаётся через `--assets`.

Для фото сначала понадобится ролик движения, например через LivePortrait и согласованную запись-образец. Готового проверенного скрипта «любой JPG сразу в наш аватар» здесь нет. Причины и источники: [ALGORITHM.md](ALGORITHM.md).
