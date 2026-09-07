"""Start only the original team pipeline and training workspace."""
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path(".env.local"))
    parser.add_argument("--port", type=int, default=8004)
    parser.add_argument("--openai-env", type=Path, help="Optional existing OpenAI configuration; credentials are not copied")
    parser.add_argument("--enable-apis", action="store_true")
    args = parser.parse_args()
    if args.env.is_file():
        os.environ["REHEARSAL_CONFIG_FILE"] = str(args.env.resolve())
        load_dotenv(args.env, override=False)
    if args.openai_env:
        for name, value in dotenv_values(args.openai_env).items():
            if name in {"OPENAI_API_KEY", "OPENAI_BASE_URL"} and value:
                os.environ[name] = value
    if args.enable_apis:
        for provider in ("OPENAI", "INWORLD"):
            os.environ[provider + "_API_ENABLED"] = "1"
    os.environ.setdefault("LOGURU_LEVEL", "WARNING")
    os.environ.setdefault("NLTK_DATA", str(Path("models/nltk_data").resolve()))
    from backend.text_app import team_source
    from backend.text_app.main import app
    from backend.text_app.models import Settings
    store = app.state.service.store
    try:
        store.get("settings", "main")
    except KeyError:
        store.put("settings", "main", Settings(voice_mode="avatar"))
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, log_level="warning")

if __name__ == "__main__":
    main()
