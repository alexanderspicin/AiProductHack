"""Portable CPU avatar runtime: finite-state search, PNG lookup, ordinary compositing.

No torch/CUDA/OpenGL/image generation is imported here. A supplied control timeline
needs only NumPy and Pillow; WAV mode additionally uses the small CPU audio driver.
"""
import argparse
from collections import OrderedDict
import json
from pathlib import Path
import subprocess
import time
import numpy as np
from PIL import Image, ImageDraw


def phase(frame, count):
    if count < 2: return 0
    k = frame % (2*count-2)
    return k if k<count else 2*count-2-k


def select_states(controls, manifest, smooth=True):
    """Receding-horizon discrete optimization, 80ms maximum lookahead at 25fps.

    E = standardized control mismatch + 0.1 * movement between adjacent states.
    The future never changes an already committed state. Silence overrides the graph.
    Out-of-coverage input is reported; the runtime does not invent missing pictures.
    """
    x=np.asarray(controls,np.float32)
    if x.ndim!=2 or x.shape[1]!=6 or not np.isfinite(x).all():
        raise ValueError('Controls must be finite [frames,6]')
    scale=np.asarray(manifest['scale'],np.float32)
    c=np.asarray(manifest['codebook'],np.float32)/scale
    emissions=((x[:,None]/scale-c[None])**2).sum(2)
    silent=np.max(np.abs(x),axis=1)<1e-8
    raw=emissions.min(1)
    emissions[silent,:]=1e8;emissions[silent,0]=0
    states=[];prev=0
    transitions=((c[:,None]-c[None])**2).sum(2)*manifest['transition_weight']
    ahead=manifest['lookahead_frames'] if smooth else 0
    for i in range(len(x)):
        end=min(len(x),i+ahead+1)
        cost=emissions[end-1].copy()
        for j in range(end-2,i-1,-1):
            cost=emissions[j]+(transitions+cost[None]).min(1)
        if smooth: cost=cost+transitions[prev]
        prev=int(cost.argmin());states.append(prev)
    return np.array(states,np.int32), {'outside_coverage_fraction':float(np.mean(raw>manifest['coverage_threshold'])) if len(x) else 0,
                                      'mean_control_error':float(raw.mean()) if len(x) else 0,
                                      'silence_frames':int(silent.sum())}


class Playback:
    """Generation fencing: cancelled/late packets can never restart speech."""
    def __init__(self): self.generation=0;self.states=[];self.active=False
    def begin(self,states):
        self.generation+=1;self.states=list(states);self.active=True
        return self.generation
    def interrupt(self):
        self.generation+=1;self.states=[];self.active=False
        return self.generation
    def state_at(self,frame,generation):
        if generation!=self.generation or not self.active or frame>=len(self.states):return 0
        return self.states[max(0,frame)]


class Avatar:
    def __init__(self,package,cache_poses=8):
        self.path=Path(package)
        self.meta=json.loads((self.path/'manifest.json').read_text())
        self.cache=OrderedDict();self.capacity=cache_poses
    def assets(self,p):
        if p in self.cache:
            self.cache.move_to_end(p);return self.cache[p]
        base=Image.open(self.path/'base'/f'{p:03d}.jpg').convert('RGB')
        sheet=Image.open(self.path/'atlas'/f'{p:03d}.png').convert('RGB')
        self.cache[p]=(base,sheet)
        while len(self.cache)>self.capacity:self.cache.popitem(last=False)
        return base,sheet
    def tile(self,p,state):
        if not 0<=state<self.meta['states']:raise ValueError('Invalid state')
        _,sheet=self.assets(p);x=(state%8)*128;y=(state//8)*128
        return sheet.crop((x,y,x+128,y+128))
    def frame(self,frame,state):
        p=phase(frame,self.meta['poses']);base,_=self.assets(p);img=base.copy()
        x1,y1,x2,y2=[round(v) for v in self.meta['rects'][p]]
        patch=self.tile(p,state).resize((x2-x1,y2-y1),Image.Resampling.BILINEAR)
        img.paste(patch,(x1,y1))
        draw=ImageDraw.Draw(img)
        draw.rectangle((0,img.height-23,img.width,img.height),fill=(20,24,30))
        draw.text((7,img.height-18),'DH Live demo | AI | research',fill='white')
        return img


def encode(avatar,states,wav,dest):
    width,height=avatar.meta['size'];fps=avatar.meta['fps']
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','pipe:0','-i',str(wav),'-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest','-movflags','+faststart',str(dest)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    timings=[];start=time.perf_counter()
    try:
        for i,k in enumerate(states):
            t=time.perf_counter();img=avatar.frame(i,int(k));timings.append((time.perf_counter()-t)*1000)
            process.stdin.write(img.tobytes())
    finally:process.stdin.close()
    if process.wait():raise RuntimeError('ffmpeg failed')
    return {'frames':len(states),'total_with_encoding_s':time.perf_counter()-start,'compose_ms_median':float(np.median(timings)), 'compose_ms_p95':float(np.quantile(timings,.95)), 'compose_ms_max':float(max(timings))}


def main():
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True)
    p.add_argument('--wav',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--controls',type=Path);args=p.parse_args()
    avatar=Avatar(args.package)
    if args.controls: controls=np.load(args.controls);timing={}
    else:
        from audio_driver import Driver
        controls,_,timing=Driver(args.package/'audio_driver.onnx').wav(args.wav)
    t=time.perf_counter();states,metrics=select_states(controls,avatar.meta)
    metrics.update({'selector_s':time.perf_counter()-t,'audio_driver':timing})
    metrics.update(encode(avatar,states,args.wav,args.out))
    args.out.with_suffix('.metrics.json').write_text(json.dumps(metrics,indent=2))
    print(json.dumps(metrics,indent=2))


if __name__=='__main__':main()
