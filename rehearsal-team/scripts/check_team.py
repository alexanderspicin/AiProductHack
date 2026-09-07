"""Local model preflight, no speech/text API calls. Use synthetic audio only."""
import argparse
import asyncio
import inspect
import json
import time
import wave
from pathlib import Path

async def main(args):
    from backend.text_app.team_pipeline import make_stt, make_user_aggregator_params, VisemeProcessor
    import numpy as np
    from backend.text_app.team_source import REPOSITORY
    result = {"external_api_calls": 0, "sources": {name: str(Path(inspect.getfile(obj)).relative_to(REPOSITORY))
              for name, obj in (("stt", make_stt), ("turn_detection", make_user_aggregator_params), ("visemes", VisemeProcessor))}}
    params = make_user_aggregator_params()
    vad = params.vad_analyzer; vad.set_sample_rate(16000)
    turn = params.user_turn_strategies.stop[0]._turn_analyzer; turn.set_sample_rate(16000)
    started = time.monotonic(); stt = make_stt()
    result["whisper_load_ms"] = round((time.monotonic()-started)*1000)
    result.update(vad=type(vad).__name__, turn=type(turn).__name__, stt=type(stt).__name__)
    if args.audio:
        with wave.open(str(args.audio)) as wav:
            assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth()) == (16000,1,2)
            audio = wav.readframes(16000 * 8)
        states = set()
        for start in range(0,len(audio),1024):
            chunk=audio[start:start+1024].ljust(1024,b'\0')
            state=await vad.analyze_audio(chunk); states.add(str(state))
            turn.append_audio(chunk,is_speech=str(state).endswith('SPEAKING'))
        started=time.monotonic(); state,metrics=await turn.analyze_end_of_turn()
        result.update(smart_turn_state=str(state), smart_turn_ms=round((time.monotonic()-started)*1000), vad_states=sorted(states))
        started=time.monotonic()
        segments,_=stt._model.transcribe(np.frombuffer(audio,dtype=np.int16).astype(np.float32)/32768,language='ru')
        result["transcript"]=' '.join(s.text.strip() for s in segments)
        result["stt_ms"]=round((time.monotonic()-started)*1000)
    await turn.cleanup()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--audio',type=Path)
    parser.add_argument('--output',type=Path,default=Path('artifacts/runs/22_team_pipeline/local-models.json'))
    asyncio.run(main(parser.parse_args()))
