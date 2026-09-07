"""One bounded Anam session using cached synthetic TTS. No LLM or paid TTS."""
import asyncio
from fractions import Fraction
import json
import logging
import re
import subprocess
from pathlib import Path
import time
import wave

import av
import httpx
import numpy as np
from anam import AnamClient, PersonaConfig, SessionOptions, AgentAudioInputConfig
from dotenv import dotenv_values

OUT = Path('artifacts/private/live-api')

async def main():
    if (OUT/'anam_ru.mp4').exists():
        raise SystemExit('Recording exists; refusing another session.')
    with wave.open(str(OUT/'inworld_ru.wav')) as wav:
        assert wav.getframerate() == 24000 and wav.getnchannels() == 1
        pcm = wav.readframes(wav.getnframes())
    config = PersonaConfig(avatar_id='30fa96d0-26c4-4e55-94a0-517025942e18',
            avatar_model='cara-4', enable_audio_passthrough=True,
            max_session_length_seconds=50)
    options = SessionOptions(enable_session_replay=False,video_quality='high',show_ai_avatar_disclosure=True)
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post('https://api.anam.ai/v1/auth/session-token',
            headers={'Authorization': 'Bearer '+dotenv_values('.env.local')['ANAM_API_KEY']},
            json={'personaConfig':config.to_dict(),'sessionOptions':options.to_dict()})
        if response.status_code not in (200,201):
            print('Token rejected',response.status_code,re.sub(r'[A-Za-z0-9_./+=-]{35,}','[REDACTED]',response.text)[:500])
            return
        client = AnamClient(session_token=response.json()['sessionToken'])
    metrics = {'scope':'cached Russian audio; API interruption, not microphone latency',
               'recording_clock':'per-track RTP anchored at first receiver arrival; approximate A/V offset'}
    started = time.monotonic()
    container = av.open(str(OUT/'anam_video.mp4'), 'w')
    audio_output = wave.open(str(OUT/'anam_audio.wav'),'wb')
    tracks = {}
    origins = {}
    spoken = asyncio.Event()
    levels = []
    try:
        async with asyncio.timeout(55):
            async with client.connect(session_options=SessionOptions(enable_session_replay=False,
                    video_quality='high',show_ai_avatar_disclosure=True)) as session:
                metrics['connected_ms'] = round((time.monotonic()-started)*1000)
                print('Connected; bounded audio/video test running.', flush=True)
                async def consume(kind):
                    frames = session.video_frames() if kind == 'video' else session.audio_frames()
                    async for frame in frames:
                        now = time.monotonic()-started
                        frame_time = float(frame.pts * frame.time_base) if frame.pts is not None else 0
                        if kind not in tracks:
                            origins[kind] = (frame_time, now)
                            if kind == 'video':
                                track = container.add_stream('libx264',rate=25)
                                track.width=frame.width; track.height=frame.height
                                track.pix_fmt='yuv420p'; track.options={'preset':'ultrafast','crf':'20'}
                                metrics['resolution']=[frame.width,frame.height]
                            else:
                                track=None
                                audio_output.setparams((frame.layout.nb_channels,2,frame.sample_rate,0,'NONE','not compressed'))
                            tracks[kind]=track
                        if kind == 'audio':
                            arr=frame.to_ndarray().astype(np.float64)
                            rms=float(np.sqrt(np.mean(arr*arr)))
                            levels.append([now,rms])
                            if rms > 200: spoken.set()
                            audio_output.writeframes(frame.to_ndarray().tobytes())
                            continue
                        else: scale=90000
                        base,offset=origins[kind]
                        frame.pts=round((frame_time-base+offset)*scale)
                        frame.time_base=Fraction(1,scale)
                        for packet in tracks[kind].encode(frame): container.mux(packet)
                jobs=[asyncio.create_task(consume('audio')),asyncio.create_task(consume('video'))]
                try:
                    stream=session.create_agent_audio_input_stream(AgentAudioInputConfig())
                    metrics['first_send_s']=time.monotonic()-started
                    for offset in range(0,len(pcm),4800): await stream.send_audio_chunk(pcm[offset:offset+4800])
                    await stream.end_sequence()
                    await asyncio.wait_for(spoken.wait(),15)
                    metrics['first_speech_s']=time.monotonic()-started
                    await asyncio.sleep(12)
                    spoken.clear()
                    stream=session.create_agent_audio_input_stream(AgentAudioInputConfig())
                    for offset in range(0,len(pcm),4800): await stream.send_audio_chunk(pcm[offset:offset+4800])
                    await stream.end_sequence()
                    await asyncio.wait_for(spoken.wait(),10)
                    await asyncio.sleep(1)
                    metrics['interrupt_sent_s']=time.monotonic()-started
                    await session.interrupt()
                    await asyncio.sleep(3)
                finally:
                    for job in jobs: job.cancel()
                    results=await asyncio.gather(*jobs,return_exceptions=True)
                    metrics['collector_errors']=[str(r)[:150] for r in results if isinstance(r,Exception)]
    except Exception as exc:
        metrics['error']=type(exc).__name__
        metrics['detail']=re.sub(r'[A-Za-z0-9_./+=-]{35,}', '[REDACTED]', str(exc))[:700]
        print('Anam test failed:',type(exc).__name__,flush=True)
    finally:
        for track in tracks.values():
            if track:
                for packet in track.encode(None): container.mux(packet)
        container.close()
        audio_output.close()
        metrics['total_seconds']=round(time.monotonic()-started,2)
        metrics['track_origins']=origins
        interrupt=metrics.get('interrupt_sent_s')
        if interrupt:
            loud=[t for t,rms in levels if t>=interrupt and rms>200]
            metrics['last_loud_frame_after_interrupt_ms']=round(max(0,max(loud,default=interrupt)-interrupt)*1000)
        (OUT/'anam_metrics.json').write_text(json.dumps(metrics,indent=2))
        (OUT/'anam_audio_levels.json').write_text(json.dumps(levels))
        if 'video' in origins and 'audio' in origins:
            subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(OUT/'anam_video.mp4'),
                '-itsoffset',str(origins['audio'][1]-origins['video'][1]),'-i',str(OUT/'anam_audio.wav'),
                '-c:v','copy','-c:a','aac','-movflags','+faststart',str(OUT/'anam_ru.mp4')],check=True)
        print(json.dumps(metrics),flush=True)

if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(main())
