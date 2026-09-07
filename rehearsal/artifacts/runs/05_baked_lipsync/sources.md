# Источники и ход поиска

Проверено 5 сентября 2026. Поиск проходил несколькими сериями: видеодубляж, подбор артикуляционных фрагментов, подготовленные 3D-представления, маленькие CPU-модели, браузерные реализации. Ниже только полезные первичные источники. Чужие заявления о скорости не приняты за наши измерения.

| Источник | Что изучено | Польза и ограничение |
|---|---|---|
| [Video Rewrite](https://chris.bregler.com/videorewrite/) | Метод, примеры, влияние размера базы | Прямой аналог подбора движений из заранее снятой записи; старое исследование, не готовый современный продукт |
| [Synthesizing Obama](https://grail.cs.washington.edu/projects/AudioToObama/siggraph17_obama.pdf) | Исследовательский подход к аудио, форме рта и совмещению с видео | Контекст для реалистичного синтеза области рта; не использовали личность или записи в эксперименте |
| [JALI](https://www.dgp.toronto.edu/~karan/jali/index.html) | Коартикуляция и разделение челюсти/губ | Объясняет, почему простая таблица букв недостаточна; коммерческий продукт, не подключали |
| [JALI, SIGGRAPH 2016](https://www.dgp.toronto.edu/~elf/JALISIG16.pdf) | Аннотация и модель артикуляции | Научное обоснование управления выразительной речью |
| [Evaluating Heuristics for Audio-Visual Translation](https://edoc.sub.uni-hamburg.de/informatik/frontdoor.php?la=de&source_opus=259) | Аннотация исследования дубляжа | Значение смыкания губ; не обещает полного совпадения произвольной речи с любым видео |
| [PS-TTS](https://arxiv.org/abs/2604.09111) | Метод согласования длительности и фонетики | Современный вариант идеи переписывать текст под видео; для учебных ответов риск изменения смысла |
| [BakedAvatar](https://buaavrcg.github.io/BakedAvatar/) | Трёхэтапный метод, мобильный вывод | Подготовленная геометрия и текстуры, графический рендер без тяжёлых полей на каждом кадре |
| [BakedAvatar, код](https://github.com/buaavrcg/BakedAvatar) | Структура и требования | Отдельная более сложная линия, не запускали |
| [LAM](https://github.com/aigc3d/LAM) | Подготовка, экспорт, WebGL; отдельно измеряемые animation/rendering | Готовая 3D-голова после GPU-подготовки; мобильный FPS не равен скорости всей цепочки аудио |
| [LAM Audio2Expression](https://github.com/aigc3d/LAM_Audio2Expression) | Аудиодрайвер и коэффициенты ARKit | Основа CPU-экспорта, использованного в нашем тесте |
| [wav2arkit CPU](https://huggingface.co/myned-ai/wav2arkit_cpu) | Model card, конфигурация, реальные веса ONNX | Запущен локально. Неофициальный объединённый экспорт, а не официальный CPU-бенчмарк Alibaba |
| [EMMA Skin](https://github.com/ryanhuge/emma-skin) | Исходники runtime, viseme/server.py, NOTICE, face-packs.md | Готовый синтетический набор для библиотеки форм рта. Маленький общественный проект, не доказанный стандарт качества |
| [DH Live](https://github.com/kleinlee/DH_live) | README, WASM, MiniLive2.js, загрузка аудио и отмена | Реально запущен браузерный пример. README говорит MIT, но есть отдельная авторизация демоаватаров/логотипа |
| [Ultralight Digital Human](https://github.com/anliyuan/Ultralight-Digital-Human) | Подготовка своего персонажа, поток, экспорт | Персональная небольшая модель; README указывает на преемника FeatherTalk |
| [FeatherTalk](https://github.com/anliyuan/FeatherTalk) | Текущий README, обучение, C++/MNN, отдельные веса персонажа | Следующий кандидат под GPU-подготовку и локальный CPU. Самостоятельно не запускали |
| [MuseTalk realtime, исходный код](https://github.com/TMElyralab/MuseTalk/blob/main/scripts/realtime_inference.py) | Кэш и инференс для нового аудио | Показательный случай: кэш не устраняет UNet и VAE-декодирование |
| [MeshTalk](https://arxiv.org/abs/2104.08223), [код](https://github.com/facebookresearch/meshtalk) | Разделение связанных и не связанных со звуком движений | Полезен архитектурно; код и данные имеют некоммерческую лицензию по README |
| [VASA-1, официальное демо](https://vasavatar.github.io/VASA-1/) | Реализм, оборудование и ограничения выпуска | Ориентир визуального качества. Демонстрация на RTX 4090, нет плана выпуска продукта/API; не кандидат для немедленного подключения |

Дополнительно просмотрены описания Instant4D, TaoAvatar/MNN, GaussianTalker и GaussianHeadTalk. Для текущего CPU-прототипа их не выбрали: отдельные требования подготовки/рендера и отсутствие проведённого нами Mac-бенчмарка. Ни их качество, ни скорость не ранжируются выше проверенных вариантов только по демонстрациям.

Примеры поисковых запросов:

```text
lip sync avatar precomputed mouth database CPU real time
Video Rewrite phoneme mouth images retrieval
BakedAvatar neural fields mobile rendering
LAM Audio2Expression ONNX CPU
github photoreal avatar sprite mouth emma skin
github DH_live mini CPU WebAssembly
lip sync dubbing isochrony phonetic synchrony bilabial consonants audiovisual translation study
JALI viseme coarticulation speech animation paper SIGGRAPH 2016
github ultralight digital human mobile cpu inference fps training ONNX
github TalkingGaussian real time inference avatar baking Gaussian talking head audio cpu
github Microsoft VASA 1 real time talking face diffusion research availability
MeshTalk cross modality disentanglement audio correlated eye blinks 2021 arxiv
```

Часть первичных страниц CVF и UW временами возвращала 403/timeout. Использованы доступные аннотации, авторские репозитории и arXiv. Статьи о дубляже не превращены в обещание, что любые слова можно безошибочно наложить на произвольную запись.
