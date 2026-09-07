# Воспроизведение

Это журнал первоначального GPU-прогона. Для нового запуска использовать [QUICKSTART.md](QUICKSTART.md) и `workflow.py`: добавлены проверка сборки, загрузка WAV, спокойное поведение и CPU-вариант предварительного расчёта.

Проверено 5 сентября 2026. Отдельный эксперимент; архитектура Pipecat не меняется. Дедлайн не задан. Исходный тайм-бокс 90 минут, завершение определялось выполнением полного GPU/CPU-цикла.

## Файлы

- `prepare.py`: синтез калибровочного звука, экспорт маленькой аудиомодели, фиксированный набор состояний, подготовка исходных кадров.
- `prompts.mjs`: геометрические карты по совместимым шейдерам DH Live.
- `bake_gpu.py`: единственный этап нейросетевой генерации изображений. Требует CUDA; 32 изображения в пакете.
- `runtime.py`: граф состояний, декодирование PNG и совмещение готовых пикселей. Нет PyTorch, OpenCV или графической модели.
- `audio_driver.py`: ONNX Runtime, явно выбран CPUExecutionProvider. Не использует CoreML.
- `evaluate.py`: три отложенные фразы, сравнение с прямым учителем и статическим ртом, видео.
- `lab.py`, `index.html`: локальный ручной тест нового текста и отмены.
- `test_runtime.py`, `browser_probe.mjs`: автоматические проверки.

## Подготовка локально

Команды выполняются из корня `rehearsal`. Сначала нужен приватный рабочий каталог. Не загружать туда ключи и персональные записи для этого эксперимента.

```sh
mkdir -p artifacts/private/07_avatar_graph/teacher_source
git clone https://github.com/kleinlee/DH_live artifacts/private/07_avatar_graph/upstream
git -C artifacts/private/07_avatar_graph/upstream archive 4a90da6e32b9cef7ed850455eddc754abed8b454 | tar -x -C artifacts/private/07_avatar_graph/teacher_source
.venv/bin/hf download ztj7728/DH_live checkpoint/DINet_mini/epoch_40.pth checkpoint/lstm/lstm_model_epoch_325.pkl --local-dir artifacts/private/07_avatar_graph/teacher_weights
uv pip install --python .venv/bin/python kaldi-native-fbank==1.22.3 onnx==1.22.0 opencv-python-headless==5.0.0.93
.venv/bin/python artifacts/runs/07_avatar_graph/prepare.py --root artifacts/private/07_avatar_graph --poses 100 --states 64
LIPSYNC_PLAYWRIGHT=@playwright/test node artifacts/runs/07_avatar_graph/prompts.mjs artifacts/private/07_avatar_graph
```

Для `prompts.mjs` нужен установленный Playwright с Chromium. `LIPSYNC_PLAYWRIGHT` может указывать на доступный пакет `@playwright/test`. В фактическом запуске использован установленный пакет соседнего локального фронтенда. Шейдеры работают на Metal только на этапе подготовки.

Версия кода выбрана намеренно. Текущий DH Live требует `epoch_40_new.pth`, а публичные найденные веса содержат старую модель. Смешивание несовместимых моделей не допускается. Проверена строгая загрузка всех весов. `torch.load` вызывается с `weights_only=True`.

Восемь калибровочных фраз дали 1115 кадров. Отложенные три фразы не участвуют в подборе центров, масштаба и порога покрытия. Параметры выбора: 64 центра, 8 шагов уточнения, вес перехода 0,1, горизонт 2 будущих кадра. Сохранённое число seed 20260905; сам подбор центров детерминированный. Малый ONNX-аудиодрайвер проверен против исходной модели, максимальная разница в исходном прогоне 0,000037.

## GPU

Использован только разрешённый личный pod. Перед запуском проверены владелец, состояние и свободная H100. Pod уже был Running; ресурсы кластера и число реплик не менялись. Из-за малого свободного места на постоянном диске все новые промежуточные файлы размещены в отдельной папке `/tmp`.

На pod нет рабочего внешнего доступа для загрузки зависимостей. Веса и входы переданы с Mac. Структура удалённой рабочей папки:

```text
teacher_source/talkingface/models/DINet_mini.py
teacher_source/mini_live/face_fusion_mask.png
teacher_source/mini_live/mouth_fusion_mask.png
teacher_weights/checkpoint/DINet_mini/epoch_40.pth
inputs/source.npy
inputs/reference.npy
inputs/prompts/
package/manifest.json
bake_gpu.py
deps/
```

Команды внутри уже проверенного личного pod; `BAKE_ROOT` задаётся путём созданной для эксперимента временной папки:

```sh
PYTHONPATH="$BAKE_ROOT/deps" /opt/python/bin/python "$BAKE_ROOT/bake_gpu.py" --root "$BAKE_ROOT" --smoke
PYTHONPATH="$BAKE_ROOT/deps" /opt/python/bin/python "$BAKE_ROOT/bake_gpu.py" --root "$BAKE_ROOT"
tar -czf "$BAKE_ROOT/result.tar.gz" -C "$BAKE_ROOT" baked
```

Среда: H100 80 ГБ, Python 3.10, PyTorch 2.1.2+cu121. Максимальная выделенная память CUDA около 172 МБ. Геометрические карты растеризуются заранее по исходным шейдерам; все итоговые лица синтезированы моделью на H100.

В исходном окружении импорт OpenCV падал из-за `libGL.so.1`. Установлен `opencv-python-headless==4.10.0.84` через скачанный на Mac Linux-wheel, с `--no-index --no-deps --target "$BAKE_ROOT/deps"`. Глобальные пакеты pod не менялись.

Первый потоковый перенос результата оборвался. Результат затем упакован в архив и полностью перенесён `kubectl cp --retries=3`; потребовались два возобновления. Архив распакован успешно. Байтовые сравнения и хеши не использовались. Корректность проверена декодированием всех атласов и загрузкой всех контрольных массивов в оценке.

После переноса:

```sh
tar -xzf artifacts/private/07_avatar_graph/result.tar.gz -C artifacts/private/07_avatar_graph
mkdir -p artifacts/private/07_avatar_graph/package/atlas
cp -R artifacts/private/07_avatar_graph/baked/atlas/. artifacts/private/07_avatar_graph/package/atlas/
```

## Независимая проверка CPU

```sh
uv venv artifacts/private/07_avatar_graph/cpu_env --python .venv/bin/python
uv pip install --python artifacts/private/07_avatar_graph/cpu_env/bin/python -r artifacts/runs/07_avatar_graph/requirements-cpu.txt
artifacts/private/07_avatar_graph/cpu_env/bin/python artifacts/runs/07_avatar_graph/evaluate.py --root artifacts/private/07_avatar_graph
/usr/bin/time -l artifacts/private/07_avatar_graph/cpu_env/bin/python artifacts/runs/07_avatar_graph/runtime.py --package artifacts/private/07_avatar_graph/package --wav artifacts/private/07_avatar_graph/inputs/new_training.wav --out artifacts/private/07_avatar_graph/isolated_cpu.mp4
artifacts/private/07_avatar_graph/cpu_env/bin/python -m unittest discover -s artifacts/runs/07_avatar_graph -p test_runtime.py -v
```

В отдельном окружении PyTorch и OpenCV отсутствуют. Наличие CoreML среди доступных провайдеров ONNX Runtime не означает его использование: драйвер явно запрашивает только CPU.

Полный независимый процесс: 4,33 с wall time; внутри этого сборка 171 кадра и кодирование видео 3,11 с. Максимальный RSS 183156736 байт, swaps 0. Длительность звука 6,81 с. Измерено на M3 Pro. Кэш проигрывателя ограничен восемью позами; основная CPU-затрата здесь приходится на распаковку PNG.

Браузерный тест после запуска `lab.py`:

```sh
LIPSYNC_PLAYWRIGHT=@playwright/test node artifacts/runs/07_avatar_graph/browser_probe.mjs artifacts/private/07_avatar_graph
```

Chromium запущен с `--disable-gpu`. Собственная фраза, отмена активного звука, отмена незавершённого запроса, повторная фраза и мобильная ширина проверены. Внешних сетевых запросов и ошибок страницы: 0. Первое обращение пришлось на ещё не готовый локальный сервер; добавлено ожидание готовности до 30 секунд.

Решение: `keep` как подтверждение архитектуры предрасчёта и CPU-воспроизведения. Качество финального персонажа и русский липсинк: `inconclusive` до человеческой оценки. Ошибки учителя нельзя принять за потери только нашего атласа.
