"""One bounded live session, synthetic input only. Uses configured OpenAI/Inworld.

No video API, no retries; <=55 seconds, one text turn plus one short audio turn.
Keep raw audio and transcripts private. Run only after authorizing API usage.
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
    if args.output.exists():
        raise SystemExit("Existing probe retained. Choose a new output only for an intentional new test.")
    with wave.open(str(args.audio)) as wav:
        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2)
        audio=wav.readframes(16000*4)
    result={"synthetic_input":True,"microphone_captured":False,"video_api_calls":0,"events":[],"viseme_frames":0,"mouth_shapes":[],"bot_words":0}
    pcm=bytearray(); sample_rate=24000; changed=asyncio.Event(); active_utterance=0
    t0=time.monotonic(); shapes=set()
    now=lambda:round((time.monotonic()-t0)*1000)
    async with httpx.AsyncClient(base_url=args.base_url,timeout=45) as http:
        started=await http.post('/api/text/sessions',json={"request_id":str(uuid4()),"scenario_id":"support","participant":"Синтетическая проверка команды","consent":True,"voice_consent":True})
        started.raise_for_status(); sid=started.json()['id']; result['session_id']=sid
        response=await http.post(f'/api/text/sessions/{sid}/voice/prepare'); response.raise_for_status()
        try:
            async with asyncio.timeout(55), websockets.connect(args.base_url.replace('http://','ws://')+response.json()['path'],origin=args.base_url) as ws:
                async def send(kind,data):
                    f=Frame(); f.message.data=json.dumps({'label':'rtvi-ai','type':kind,'id':str(uuid4()),'data':data})
                    await ws.send(f.SerializeToString())
                async def read():
                    nonlocal sample_rate,active_utterance
                    async for raw in ws:
                        f=Frame.FromString(raw); kind=f.WhichOneof('frame')
                        if kind=='audio':
                            sample_rate=f.audio.sample_rate
                            if len(pcm)<sample_rate*2*55: pcm.extend(f.audio.audio)
                            key=f'audio_{active_utterance}_ms'
                            if key not in result: result[key]=now()
                            changed.set(); continue
                        if kind!='message': continue
                        msg=json.loads(f.message.data); typ=msg.get('type'); data=msg.get('data') or {}
                        if typ=='server-message':
                            typ='avatar_'+str(data.get('type')); active_utterance=data.get('utterance_id',active_utterance)
                            if typ=='avatar_viseme':
                                result['viseme_frames']+=1
                                shapes.update(k for k,v in data.get('blendshapes',{}).items() if k.startswith('viseme_') and v>.1)
                                continue
                        if typ=='bot-tts-text': result['bot_words']+=1
                        if typ in {'bot-ready','bot-started-speaking','bot-stopped-speaking','user-started-speaking','user-stopped-speaking','user-transcription','avatar_playback_start','avatar_interrupt','avatar_playback_end','error'}:
                            event={'kind':typ,'at_ms':now(),'utterance_id':active_utterance}
                            if typ=='user-transcription': event['text']=data.get('text')
                            result['events'].append(event)
                            changed.set()
                async def until(predicate,timeout=20):
                    async with asyncio.timeout(timeout):
                        while not predicate():
                            changed.clear(); await changed.wait()
                reader=asyncio.create_task(read())
                try:
                    await send('client-ready',{'version':'2.1.0','about':{'library':'team-synthetic-probe'}})
                    await until(lambda:bool(pcm))
                    # Let asynchronous Inworld word timings arrive before cutting the greeting.
                    await asyncio.sleep(.8)
                    result['manual_interrupt_sent_ms']=now()
                    await send('client-message',{'t':'interrupt'})
                    await until(lambda:any(e['kind']=='avatar_interrupt' for e in result['events']),5)
                    result['text_sent_ms']=now()
                    await send('send-text',{'content':'Здравствуйте. Понимаю, что ждать неприятно. Подскажите, на каком шаге появляется ошибка?','options':{'run_immediately':True,'audio_response':True}})
                    await until(lambda:any(k.startswith('audio_') and v>result['text_sent_ms'] for k,v in result.items() if isinstance(v,(int,float))))
                    result['input_start_ms']=now(); begin=time.monotonic()
                    data=audio+b'\0'*(32000*4)
                    for offset in range(0,len(data),1024):
                        f=Frame(); f.audio.audio=data[offset:offset+1024].ljust(1024,b'\0');f.audio.sample_rate=16000;f.audio.num_channels=1
                        await ws.send(f.SerializeToString());await asyncio.sleep(max(0,begin+(offset+1024)/32000-time.monotonic()))
                    await until(lambda:any(e['kind']=='user-transcription' for e in result['events']),12)
                    await until(lambda:any(e['kind']=='bot-stopped-speaking' and e['at_ms']>result['input_start_ms']+8000 for e in result['events']),15)
                finally:
                    reader.cancel();await asyncio.gather(reader,return_exceptions=True)
        except Exception as exc:
            result['error_type']=type(exc).__name__
        finally:
            result['stop_status']=(await http.post(f'/api/text/sessions/{sid}/voice/stop')).status_code
            ending=await http.post(f'/api/text/sessions/{sid}/end');result['end_status']=ending.status_code
            result['session']=(await http.get(f'/api/text/sessions/{sid}')).json()
    start=next((e['at_ms'] for e in result['events'] if e['kind']=='user-started-speaking'),None)
    transcript=next((e['at_ms'] for e in result['events'] if e['kind']=='user-transcription'),None)
    interrupt=next((e['at_ms'] for e in result['events'] if e['kind']=='avatar_interrupt'),None)
    result.update(mouth_shapes=sorted(shapes),audio_seconds=len(pcm)/(sample_rate*2),sample_rate=sample_rate,
        manual_interrupt_ack_ms=interrupt-result['manual_interrupt_sent_ms'] if interrupt is not None and 'manual_interrupt_sent_ms' in result else None,
        input_to_vad_ms=start-result['input_start_ms'] if start is not None and 'input_start_ms' in result else None,
        vad_before_transcription=start is not None and transcript is not None and start<transcript)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if pcm:
        with wave.open(str(args.output.with_suffix('.wav')),'wb') as wav:
            wav.setparams((1,2,sample_rate,0,'NONE','not compressed'));wav.writeframes(pcm)
    print(json.dumps({k:v for k,v in result.items() if k!='session'},ensure_ascii=False,indent=2))
    print('Report:',result['session'].get('report_status'),'Turns:',len(result['session'].get('turns',[])))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:8004');parser.add_argument('--audio',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    asyncio.run(probe(parser.parse_args()))
