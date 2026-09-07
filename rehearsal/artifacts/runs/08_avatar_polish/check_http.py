"""Local integration checks. No external requests, credentials or paid TTS."""
import argparse
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import wave


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8897);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();base=f'http://127.0.0.1:{args.port}';opener=urllib.request.build_opener(NoRedirect);checks={}
    def request(path,method='GET',body=None,headers=None):
        req=urllib.request.Request(base+path,data=body,method=method,headers=headers or {})
        try:res=opener.open(req,timeout=30)
        except urllib.error.HTTPError as e:res=e
        with res:return res.status,dict(res.headers),res.read()
    code,headers,body=request('/comparison.webm','HEAD')
    assert code==200 and not body and headers['Accept-Ranges']=='bytes' and int(headers['Content-Length'])>1000
    checks['head']=True
    for target in ['/comparison.webm','/comparison.mp4']:
        code,h,body=request(target,headers={'Range':'bytes=0-1023'})
        assert code==206 and len(body)==1024 and h['Content-Range'].startswith('bytes 0-1023/')
    checks['range_both_formats']=True
    code,_,_=request('/comparison.mp4',headers={'Range':'bytes=999999999-'});assert code==416
    checks['unsatisfiable_range']=True
    code,h,_=request('/comparison.mp4',headers={'Accept':'text/html'});assert code==302 and h['Location']=='/examples?clip=comparison'
    checks['legacy_link_redirect']=True
    for path in ['/assets/../../.env','/clips/../manifest.json','/not-found']:
        assert request(path)[0]==404
    checks['path_whitelist']=True
    assert request('/speak','POST',b'{}',{'Content-Type':'application/json','Origin':'https://example.org'})[0]==403
    checks['cross_origin_rejected']=True
    assert request('/animate-audio','POST',b'x'*80,{'Content-Type':'audio/wav'})[0]==400
    assert request('/animate-audio','POST',b'x'*80,{'Content-Type':'audio/mpeg'})[0]==415
    checks['invalid_audio_rejected']=True
    raw=(args.root/'inputs/new_closures.wav').read_bytes()
    start=time.monotonic();code,_,body=request('/animate-audio','POST',raw,{'Content-Type':'audio/wav'})
    assert code==200,body;result=json.loads(body)
    assert len(result['states'])>100 and len(set(result['states']))>3
    assert request(result['audio'],'HEAD')[0]==200
    checks['valid_mono_wav']=True;checks['mono_wall_s']=time.monotonic()-start;checks['mono_prepare_s']=result['prepare_s'];checks['mono_frames']=len(result['states'])
    with wave.open(io.BytesIO(raw),'rb') as src:
        rate=src.getframerate();pcm=src.readframes(src.getnframes())
    stereo=b''.join(pcm[i:i+2]*2 for i in range(0,len(pcm),2));buf=io.BytesIO()
    with wave.open(buf,'wb') as dst:dst.setnchannels(2);dst.setsampwidth(2);dst.setframerate(rate);dst.writeframes(stereo)
    assert request('/animate-audio','POST',buf.getvalue(),{'Content-Type':'audio/wav'})[0]==200
    checks['valid_stereo_wav']=True
    buf=io.BytesIO()
    with wave.open(buf,'wb') as dst:dst.setnchannels(1);dst.setsampwidth(2);dst.setframerate(8000);dst.writeframes(b'\0\0'*(46*8000))
    assert request('/animate-audio','POST',buf.getvalue(),{'Content-Type':'audio/wav'})[0]==400
    checks['duration_guard']=True
    code,_,body=request('/speak','POST',json.dumps({'text':'Мама попросила Павла купить молоко.'}).encode(),{'Content-Type':'application/json'})
    assert code==200,body;spoken=json.loads(body)
    assert spoken['timing']['duration_s']>1 and len(set(spoken['states']))>3
    checks['local_tts_non_silent']=True;checks['local_tts_prepare_s']=spoken['prepare_s'];checks['paid_calls']=0
    args.out.write_text(json.dumps(checks,indent=2));print(json.dumps(checks,indent=2))


if __name__=='__main__':main()
