"""Bounded paid smoke: one <=500-char synthetic phrase; no automatic retry."""
import asyncio
import base64
import json
import time
import wave
from pathlib import Path

import httpx
from dotenv import dotenv_values

TEXT = 'Добрый день! Понимаю ваши сомнения. Давайте спокойно разберёмся: что именно вас беспокоит? Мы можем начать с небольшой группы и обсудить результат через неделю.'
OUT = Path('artifacts/private/live-api')

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'inworld_ru.wav'
    if target.exists():
        raise SystemExit('Existing sample retained; no duplicate paid request.')
    assert len(TEXT) <= 500
    key = dotenv_values('.env.local')['INWORLD_API_KEY']
    payload = dict(text=TEXT, voiceId='Svetlana', modelId='inworld-tts-2',
                   audioConfig=dict(audioEncoding='PCM', sampleRateHertz=24000),
                   timestampType='WORD', timestampTransportStrategy='SYNC')
    started = time.perf_counter()
    pcm = bytearray()
    stamps = []
    first = None
    async with httpx.AsyncClient(timeout=40) as client:
        async with client.stream('POST', 'https://api.inworld.ai/tts/v1/voice:stream',
                                 headers={'Authorization': f'Basic {key}'}, json=payload) as response:
            if response.status_code != 200:
                raise SystemExit(f'Inworld HTTP {response.status_code}; no retry.')
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                result = json.loads(line).get('result', {})
                if result.get('audioContent'):
                    first = first or time.perf_counter() - started
                    pcm.extend(base64.b64decode(result['audioContent']))
                if result.get('timestampInfo'):
                    stamps.append(result['timestampInfo'])
    if not pcm or pcm[:4] == b'RIFF':
        raise SystemExit('Unexpected audio format; inspect before playback.')
    with wave.open(str(target), 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm)
    metrics = dict(text=TEXT, chars=len(TEXT), voice='Svetlana', model='inworld-tts-2',
                   first_audio_ms=round(first*1000), total_ms=round((time.perf_counter()-started)*1000),
                   audio_seconds=len(pcm)/48000, estimated_usd=len(TEXT)*25/1_000_000,
                   timestamp_messages=len(stamps))
    (OUT/'inworld_metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    (OUT/'inworld_timestamps.json').write_text(json.dumps(stamps, ensure_ascii=False, indent=2))
    print(json.dumps(metrics, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(main())
