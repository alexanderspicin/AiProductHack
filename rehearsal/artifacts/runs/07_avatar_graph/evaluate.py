"""Held-out teacher comparison; objective approximation error, NOT a realism score."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time
import numpy as np
from PIL import Image, ImageDraw
from runtime import Avatar, phase, select_states, encode
from audio_driver import Driver


def errors(images,teacher):
    # Upstream neural synthesis acts on the central 72x72 mouth region.
    a=images[:,28:100,28:100].astype(np.float32)
    b=teacher[:,28:100,28:100].astype(np.float32)
    mse=float(np.mean((a-b)**2))
    return {'mouth_mae_0_255':float(np.mean(np.abs(a-b))),
            'mouth_psnr_db':float(10*np.log10(255**2/max(mse,1e-9))),
            'temporal_delta_mae_0_255':float(np.mean(np.abs(np.diff(a,axis=0)-np.diff(b,axis=0))))}


def comparison(avatar,teacher,nearest,smooth,wav,dest):
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x580','-r','25','-i','pipe:0','-i',str(wav),'-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-shortest','-movflags','+faststart',str(dest)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for i,(raw,smoothstate) in enumerate(zip(nearest,smooth)):
        p=phase(i,avatar.meta['poses']);base,_=avatar.assets(p)
        img=Image.new('RGB',(1080,580),'#f1f3ed');draw=ImageDraw.Draw(img)
        direct=base.copy();r=[round(v) for v in avatar.meta['rects'][p]]
        direct.paste(Image.fromarray(teacher[i]).resize((r[2]-r[0],r[3]-r[1]),Image.Resampling.BILINEAR),(r[0],r[1]))
        for j,(frame,label) in enumerate([(direct,'GPU teacher (reference)'),(avatar.frame(i,int(raw)),'Cached: nearest state'),(avatar.frame(i,int(smoothstate)),'Cached: temporal graph')]):
            img.paste(frame,(j*360,40));draw.text((j*360+12,12),label,fill='#203b30')
        draw.text((10,560),'DH Live demo | AI | research',fill='#203b30')
        process.stdin.write(img.tobytes())
    process.stdin.close()
    if process.wait():raise RuntimeError('Comparison encode failed')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    root=args.root.resolve();avatar=Avatar(root/'package');driver=Driver(root/'package/audio_driver.onnx')
    all_metrics={};timings=[]
    for name in avatar.meta['heldout']:
        controls,_,audio_timing=driver.wav(root/f'inputs/{name}.wav')
        teacher=np.load(root/f'baked/{name}_teacher.npy')
        nearest,coverage=select_states(controls,avatar.meta,smooth=False)
        t=time.perf_counter();smooth,_=select_states(controls,avatar.meta);selector_s=time.perf_counter()-t
        tile_data={}
        for label,states in [('nearest',nearest),('temporal_graph',smooth),('neutral_only',np.zeros(len(smooth),int))]:
            tiles=[]
            for i,k in enumerate(states):
                t=time.perf_counter();tiles.append(np.asarray(avatar.tile(phase(i,avatar.meta['poses']),int(k))));timings.append((time.perf_counter()-t)*1000)
            tile_data[label]=np.stack(tiles)
        result={label:errors(tiles,teacher) for label,tiles in tile_data.items()}
        result.update({'coverage':coverage,'audio_driver':audio_timing,'selector_s':selector_s})
        result['render']=encode(Avatar(root/'package'),smooth,root/f'inputs/{name}.wav',root/f'{name}_cpu.mp4')
        if name=='new_training':
            comparison(avatar,teacher,nearest,smooth,root/f'inputs/{name}.wav',root/'comparison.mp4')
            indices=[10,30,50,80,110,150]
            sheet=Image.new('RGB',(6*128,3*150),'white');draw=ImageDraw.Draw(sheet)
            for row,(label,images) in enumerate([('teacher',teacher),('nearest',tile_data['nearest']),('graph',tile_data['temporal_graph'])]):
                for col,i in enumerate(indices):sheet.paste(Image.fromarray(images[min(i,len(images)-1)]),(col*128,row*150+22))
                draw.text((4,row*150+4),label,fill='black')
            sheet.save(root/'comparison_contact.png')
        all_metrics[name]=result
    all_metrics['resources']={'package_mb':sum(p.stat().st_size for p in (root/'package').rglob('*') if p.is_file())/1e6,
                              'runtime_peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6,
                              'tile_decode_ms_median':float(np.median(timings)), 'tile_decode_ms_p95':float(np.quantile(timings,.95)),
                              'memory_note':'Mac ru_maxrss bytes; includes evaluation arrays and reference video, not isolated player'}
    (root/'evaluation.json').write_text(json.dumps(all_metrics,indent=2));print(json.dumps(all_metrics,indent=2))


if __name__=='__main__':main()
