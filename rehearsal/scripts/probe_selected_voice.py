"""One bounded live voice probe using an existing SYNTHETIC WAV, never the microphone.

Uses free Cartesia quota and the configured text API; no video session is created.
Writes only event timing and synthetic transcript. No keys or temporary tokens.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4
import wave

import httpx
import websockets
from pipecat.frames.protobufs.frames_pb2 import Frame


async def probe(args):
    with wave.open(str(args.audio), 'rb') as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Need synthetic WAV PCM16 mono 16000 Hz')
        audio = wav.readframes(16000 * 8)
    result = {'kind': 'synthetic_audio_only', 'microphone_captured': False, 'avatar_calls': 0, 'events': []}
    request_id = str(uuid4())
    async with httpx.AsyncClient(base_url=args.base_url, timeout=45) as http:
        started = await http.post('/api/text/sessions', json={'request_id':str(uuid4()), 'scenario_id':'sales-objection',
            'participant':'Проверка синтетической речи', 'consent':True, 'voice_consent':True})
        started.raise_for_status(); sid = started.json()['id']; result['session_id'] = sid
        prepared = await http.post(f'/api/text/sessions/{sid}/voice/prepare', json={'request_id':request_id, 'audio_only':True})
        prepared.raise_for_status()
        t0 = time.monotonic(); speech_start = None
        got_audio = asyncio.Event(); resumed = asyncio.Event()
        uri = args.base_url.replace('http://', 'ws://') + prepared.json()['path']
        try:
            async with asyncio.timeout(45), websockets.connect(uri, origin=args.base_url) as ws:
                async def message(kind, data):
                    frame = Frame(); frame.message.data = json.dumps({'label':'rtvi-ai','type':kind,'id':str(uuid4()),'data':data})
                    await ws.send(frame.SerializeToString())

                async def reader():
                    async for raw in ws:
                        frame = Frame.FromString(raw)
                        if frame.WhichOneof('frame') != 'message':
                            continue
                        msg = json.loads(frame.message.data); kind = msg.get('type'); data = msg.get('data') or {}
                        now = round((time.monotonic() - t0) * 1000)
                        if kind in {'user-started-speaking','user-stopped-speaking','vad-user-started-speaking','vad-user-stopped-speaking','user-transcription','error'}:
                            event = {'kind':kind,'at_ms':now}
                            if kind == 'user-transcription': event['text'] = data.get('text')
                            result['events'].append(event)
                        if kind == 'server-message' and data.get('type') == 'avatar_audio':
                            if data.get('kind') == 'chunk': got_audio.set()
                            if data.get('kind') in {'start','interrupt','end'}:
                                result['events'].append({'kind':'avatar_' + data['kind'],'epoch':data['epoch'],'at_ms':now})
                            if data.get('kind') == 'chunk' and speech_start is not None and data['epoch'] > 0:
                                result.setdefault('new_audio_at_ms', now); resumed.set()
                read_task = asyncio.create_task(reader())
                try:
                    await message('client-ready', {'version':'2.1.0','about':{'library':'rehearsal-synthetic-probe'}})
                    await asyncio.wait_for(got_audio.wait(), 22)
                    await asyncio.sleep(.35)
                    speech_start = time.monotonic(); result['input_start_ms'] = round((speech_start - t0) * 1000)
                    # Real-time packet pacing, then silence so Smart Turn and Whisper can finish.
                    pcm = audio + b'\0' * (16000 * 2 * 4)
                    for offset in range(0, len(pcm), 1024):
                        frame = Frame(); frame.audio.audio = pcm[offset:offset+1024].ljust(1024,b'\0')
                        frame.audio.sample_rate = 16000; frame.audio.num_channels = 1
                        await ws.send(frame.SerializeToString())
                        await asyncio.sleep(max(0, speech_start + (offset+1024)/32000 - time.monotonic()))
                    await asyncio.wait_for(resumed.wait(), 12)
                    await asyncio.sleep(2)
                finally:
                    read_task.cancel()
                    await asyncio.gather(read_task, return_exceptions=True)
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        finally:
            stop = await http.post(f'/api/text/sessions/{sid}/voice/stop', json={'request_id':request_id})
            result['stop_status'] = stop.status_code
            session = (await http.get(f'/api/text/sessions/{sid}')).json()
            result['turns'] = session.get('turns', [])
            # Leave the saved training available for inspection; do not request automatic grading.
        events = result['events']; begin = result.get('input_start_ms', 0)
        start = next((e['at_ms'] for e in events if e['kind']=='user-started-speaking'), None)
        transcript = next((e['at_ms'] for e in events if e['kind']=='user-transcription'), None)
        result['input_to_user_started_ms'] = start - begin if start is not None else None
        result['start_before_transcript'] = start is not None and transcript is not None and start < transcript
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8003')
    parser.add_argument('--audio', type=Path, required=True, help='Existing synthetic audio only, not personal recordings')
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(probe(parser.parse_args()))
