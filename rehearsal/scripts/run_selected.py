"""Local launcher. Read existing keys without copying them or printing values."""
import argparse
import os
from pathlib import Path

from dotenv import dotenv_values
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--openai-env', type=Path, default=Path('.env.local'))
    parser.add_argument('--voice-env', type=Path, default=Path('.env.local'))
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--enable-apis', action='store_true', help='Explicitly enable existing API credentials for interactive tests')
    args = parser.parse_args()
    for path, names in ((args.openai_env, ['OPENAI_API_KEY', 'OPENAI_BASE_URL']),
                        (args.voice_env, ['CARTESIA_API_KEY', 'TAVUS_API_KEY', 'ANAM_API_KEY', 'INWORLD_API_KEY', 'TAVUS_PAL_ID'])):
        values = dotenv_values(path)
        for name in names:
            if values.get(name):
                os.environ[name] = values[name]
    if args.enable_apis:
        for provider in ('OPENAI', 'CARTESIA', 'TAVUS', 'ANAM'):
            os.environ[provider + '_API_ENABLED'] = '1'
    os.environ['AVATAR_SESSION_SECONDS'] = str(min(180, max(30, args.seconds)))
    # Provider exceptions must never log keys, signed URLs or full transcripts.
    os.environ.setdefault('LOGURU_LEVEL', 'WARNING')
    os.environ.setdefault('NLTK_DATA', str(Path('models/nltk_data').resolve()))
    import nltk
    try:
        nltk.data.find('tokenizers/punkt_tab/english')
    except LookupError:
        parser.error('Нет punkt_tab. Установите данные NLTK по инструкции docs/SELECTED_AVATARS.md.')
    uvicorn.run('backend.text_app.main:app', host='127.0.0.1', port=args.port, workers=1, log_level='warning')


if __name__ == '__main__':
    main()
