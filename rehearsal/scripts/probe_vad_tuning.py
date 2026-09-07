"""Bounded offline comparison. No TTS, LLM, camera or microphone calls."""
import argparse
import asyncio
import json
from pathlib import Path
import wave
import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState

async def main(args):
    with wave.open(str(args.audio), 'rb') as wav:
        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth()) == (16000,1,2)
        speech = wav.readframes(wav.getnframes())
    rng = np.random.default_rng(42)
    controls = {'silence': bytes(96000), 'quiet_noise': (rng.normal(0, .012, 48000) * 32767).astype(np.int16).tobytes()}
    rows=[]
    for confidence, start_secs, min_volume in [(0.7,.1,.6),(.55,.08,.6),(.5,.08,.45)]:
        row={'confidence':confidence,'start_secs':start_secs,'min_volume':min_volume}
        for name, audio in {'synthetic_ru':speech,**controls}.items():
            vad=SileroVADAnalyzer(params=VADParams(confidence=confidence,start_secs=start_secs,stop_secs=.2,min_volume=min_volume))
            vad.set_sample_rate(16000); onset=None
            for offset in range(0,len(audio),1024):
                state=await vad.analyze_audio(audio[offset:offset+1024].ljust(1024,b'\0'))
                if state == VADState.SPEAKING and onset is None: onset=round((offset+1024)/32)
            row[name+'_first_speaking_ms']=onset
        rows.append(row)
    result={'seed':42,'external_calls':0,'input':'existing_synthetic_ru_16k','results':rows,
        'limitation':'One synthetic speaker and synthetic noise controls. Not real-room false positive rate.'}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    asyncio.run(main(p.parse_args()))
