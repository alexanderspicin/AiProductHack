# Доступ к экспериментам

2026-09-05. Пользователь разрешил небольшие реальные расходы. Принят консервативный потолок 100 RUB суммарно, сначала бесплатные квоты. Это ограничение плана, не уже установленный биллинг-порог. Подписки и минимальные пополнения сверх потолка требуют отдельного согласования. Запросы генерации и платежи в этом шаге не выполнялись.

Первые доступы: Inworld (ключ команды) и Anam; затем ElevenLabs или Cartesia. Полный список кабинетов:

- ElevenLabs: https://elevenlabs.io/app — Developers / API Keys, TTS и чтение голосов. https://elevenlabs.io/docs/help-center/technical/how-do-i-authorize-myself-using-an-api-key
- Cartesia: https://play.cartesia.ai/keys — обычный API key, не admin. https://docs.cartesia.ai/use-the-api/api-conventions
- Inworld: https://platform.inworld.ai — API Keys, Basic Base64 signature. https://docs.inworld.ai/quickstart-tts
- Fish: https://fish.audio/app/api-keys/ — API key. https://docs.fish.audio/api-reference/introduction
- Hume: https://app.hume.ai — API Keys, API key без Secret key для серверного TTS. https://dev.hume.ai/docs/introduction/api-key
- Anam: https://lab.anam.ai — API key и выбранный avatar ID. https://anam.ai/docs/javascript-sdk/quickstart
- LiveAvatar: https://app.liveavatar.com — API key, доступ к LITE и avatar ID. https://docs.liveavatar.com/docs/faq/api-key
- Tavus: https://maker.tavus.io — API Key. Текущая страница авторизации перенаправляет в PAL Maker; доступ к нужному режиму нужно проверить до оплаты. https://docs.tavus.io/api-reference/authentication
- Simli: https://app.simli.com — API key и face ID; прежний ключ проверить локально, не просить пересылать повторно.
- D-ID: https://studio.d-id.com — Account settings / Generate API key, полное значение API_USER:API_PASSWORD. https://docs.d-id.com/docs/api-keys

Хранение: добавлять ключи в локальный .env.local, не в чат или GitHub, не перезаписывать существующие строки. Конкретные адаптеры ещё не подключены: имена переменных для новых поставщиков будут согласованы с кодом. Пароли кабинетов, платёжные реквизиты и cookies не нужны. Для первого сравнения использовать стандартные лицензированные лица и голоса, обучение/клонирование не оплачивать.
