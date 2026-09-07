"""Loopback-only CPU lab. No paid API and no image model on the request path."""
import argparse
import io
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlparse
import uuid
import wave
from audio_driver import Driver
from runtime import Avatar, select_states
from media_http import send_file


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--port',type=int,default=8897)
    args=parser.parse_args();root=args.root.resolve();package=root/'package';clips=root/'user_clips';clips.mkdir(exist_ok=True)
    avatar=Avatar(package);driver=Driver(package/'audio_driver.onnx');slots=threading.BoundedSemaphore(2)
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,data,kind='application/json'):
            if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-cache')
            self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_HEAD(self):self.do_GET(head=True)
        def do_GET(self,head=False):
            target=urlparse(self.path).path
            if target=='/comparison.mp4' and 'text/html' in self.headers.get('Accept',''):
                self.send_response(302);self.send_header('Location','/examples?clip=comparison')
                self.send_header('Content-Length','0');self.end_headers();return
            if target=='/':file=Path(__file__).with_name('index.html')
            elif target=='/examples':file=Path(__file__).with_name('examples.html')
            elif target=='/motion.js':file=Path(__file__).with_name('motion.js')
            elif target=='/manifest.json':file=package/'manifest.json'
            elif re.fullmatch(r'/assets/(base/\d{3}\.jpg|atlas/\d{3}\.png)',target):file=package/target[len('/assets/'):]
            elif re.fullmatch(r'/clips/[a-f0-9]{32}\.wav',target):file=clips/target.rsplit('/',1)[1]
            elif re.fullmatch(r'/(comparison|new_training_cpu|new_closures_cpu|new_rounding_cpu)\.(mp4|webm)',target):file=root/target[1:]
            elif target=='/comparison_poster.jpg':file=root/'comparison_poster.jpg'
            else:return self.reply(404,{'error':'Not found'})
            if not file.is_file():return self.reply(404,{'error':'Not ready'})
            send_file(self,file,head=head)
        def do_POST(self):
            if self.path not in ['/speak','/animate-audio']:return self.reply(404,{'error':'Not found'})
            origin=self.headers.get('Origin')
            if origin and origin not in [f'http://127.0.0.1:{args.port}',f'http://localhost:{args.port}']:
                return self.reply(403,{'error':'Origin rejected'})
            if self.path=='/animate-audio':return self.animate_audio()
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,{'error':'Expected JSON'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192:raise ValueError('Некорректный размер запроса')
                text=json.loads(self.rfile.read(length)).get('text')
                if not isinstance(text,str) or not 1<=len(text.strip())<=600:raise ValueError('Введите от 1 до 600 символов')
            except (ValueError,TypeError,AttributeError) as e:return self.reply(400,{'error':str(e)})
            if not slots.acquire(blocking=False):return self.reply(429,{'error':'Подождите завершения предыдущего запроса'})
            try:
                start=time.perf_counter();ident=uuid.uuid4().hex;wav=clips/f'{ident}.wav';aiff=clips/f'{ident}.aiff'
                subprocess.run(['say','-v','Milena','-r','165','-o',str(aiff),'--',text.strip()],check=True,timeout=30,capture_output=True)
                subprocess.run(['ffmpeg','-v','error','-y','-i',str(aiff),'-af','apad=pad_dur=0.4','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True,timeout=30,capture_output=True)
                controls,silent,timing=driver.wav(wav)
                if silent.all():return self.reply(500,{'error':'macOS вернул тишину. Запустите сервер из обычного терминала или загрузите готовый WAV.'})
                states,metrics=select_states(controls,avatar.meta)
                result={'audio':f'/clips/{ident}.wav','states':states.tolist(),'metrics':metrics,'timing':timing,'prepare_s':time.perf_counter()-start}
                (clips/f'{ident}.json').write_text(json.dumps({'text':text,**result},ensure_ascii=False,indent=2))
                self.reply(200,result)
            except (subprocess.SubprocessError,ValueError) as e:self.reply(500,{'error':type(e).__name__+': локальная подготовка речи не удалась'})
            finally:slots.release()
        def animate_audio(self):
            if self.headers.get('Content-Type','').split(';')[0]!='audio/wav':return self.reply(415,{'error':'Нужен PCM16 WAV'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 44<=length<=10*1024*1024:raise ValueError('WAV должен быть меньше 10 МБ')
                payload=self.rfile.read(length)
                with wave.open(io.BytesIO(payload),'rb') as audio:
                    if audio.getsampwidth()!=2 or audio.getnchannels() not in [1,2]:raise ValueError('Нужен PCM16 mono/stereo WAV')
                    if not 8000<=audio.getframerate()<=96000 or not 0<audio.getnframes()/audio.getframerate()<=45:raise ValueError('Длительность до 45 с, частота 8–96 кГц')
            except (ValueError,wave.Error,EOFError) as e:return self.reply(400,{'error':str(e)})
            if not slots.acquire(blocking=False):return self.reply(429,{'error':'Подождите завершения предыдущего запроса'})
            try:
                start=time.perf_counter();ident=uuid.uuid4().hex;raw=clips/f'{ident}_input.wav';wav=clips/f'{ident}.wav';raw.write_bytes(payload)
                subprocess.run(['ffmpeg','-v','error','-y','-protocol_whitelist','file,pipe','-f','wav','-i',str(raw),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True,timeout=20,capture_output=True)
                controls,_,timing=driver.wav(wav);selected,metrics=select_states(controls,avatar.meta)
                result={'audio':f'/clips/{ident}.wav','states':selected.tolist(),'metrics':metrics,'timing':timing,'prepare_s':time.perf_counter()-start}
                (clips/f'{ident}.json').write_text(json.dumps({'input':'user-supplied local WAV',**result},indent=2));self.reply(200,result)
            except (subprocess.SubprocessError,ValueError):self.reply(500,{'error':'Не удалось обработать локальный WAV'})
            finally:slots.release()
        def log_message(self,fmt,*values):
            # Request bodies (potential user text) and secrets are never logged.
            print(fmt%values,flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'CPU atlas lab: http://127.0.0.1:{args.port}',flush=True)
    server.serve_forever()


if __name__=='__main__':main()
