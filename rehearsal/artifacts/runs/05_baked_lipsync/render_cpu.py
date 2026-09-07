"""CPU-only cached mouth compositor and portable audio/video evidence.

Asset attribution: EMMA Skin / Ryan Chen, Apache-2.0. This is a new experimental
renderer using its nearest-shape formula. No portrait regeneration at runtime.
"""
import json
import math
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw
from lab import HERE, PRIVATE

ASSETS = PRIVATE / 'vendor/emma'
meta = json.loads((ASSETS / 'mouth-sprites.json').read_text())
eye_meta = json.loads((ASSETS / 'eyes.json').read_text())
base = Image.open(ASSETS / 'base.png').convert('RGBA').resize((416, 608))
place = {k: round(v / 2) for k, v in meta['placement'].items()}
mouths = [(s, Image.open(ASSETS / 'mouth-sprites' / s['file']).convert('RGBA').resize((place['w'], place['h']))) for s in meta['sprites']]
eye_place = {k: round(v/2) for k,v in eye_meta['placement'].items()}
eyes = [Image.open(ASSETS/'eyes'/s['file']).convert('RGBA').resize((eye_place['w'],eye_place['h'])) for s in eye_meta['sprites']]


def frame(row, index):
    distances = [((s['openness'] - row[0])*1.6)**2 + ((s['width'] - row[1])*.7)**2 + ((s['roundness'] - row[2])*.7)**2 for s,_ in mouths]
    a,b = np.argsort(distances)[:2]
    x,y = math.sqrt(distances[a]),math.sqrt(distances[b])
    weight = x/(x+y) if x+y else 0
    im = base.copy()
    im.alpha_composite(mouths[a][1], (place['x'],place['y']))
    if weight > .01:
        patch = mouths[b][1].copy()
        patch.putalpha(patch.getchannel('A').point(lambda v: round(v*weight)))
        im.alpha_composite(patch, (place['x'],place['y']))
    phase = (index/30) % 4.1
    eye = eyes[2 if phase < .075 else 1 if phase < .145 else 0]
    im.alpha_composite(eye, (eye_place['x'],eye_place['y']))
    return im.convert('RGB')


if __name__ == '__main__':
    entry = json.loads((PRIVATE/'training.json').read_text())
    result = {'dimensions': [416,608], 'fps': 30, 'render': 'Pillow CPU', 'encode': 'libx264 CPU, 2 threads', 'variants': []}
    for variant in ('energy', 'model'):
        dest = PRIVATE / f'cpu_{variant}.mp4'
        cmd = ['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','416x608','-r','30','-i','pipe:0',
               '-i',str(PRIVATE/'training.wav'),'-c:v','libx264','-threads','2','-preset','fast','-crf','18','-pix_fmt','yuv420p',
               '-c:a','aac','-shortest','-movflags','+faststart',str(dest)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = time.perf_counter(); timings=[]
        for i, row in enumerate(entry[variant]):
            tick = time.perf_counter(); im=frame(row,i); timings.append((time.perf_counter()-tick)*1000)
            proc.stdin.write(im.tobytes())
        proc.stdin.close()
        assert proc.wait(timeout=30)==0
        wall=time.perf_counter()-t0
        result['variants'].append({'variant':variant,'frames':len(timings),'compose_median_ms':float(np.median(timings)),
                                   'compose_p95_ms':float(np.percentile(timings,95)), 'compose_encode_total_s':wall,
                                   'end_to_end_render_fps':len(timings)/wall,'output_bytes':dest.stat().st_size})
    # Mouth-state inspection, not a perceptual metric.
    sheet=Image.new('RGB',(416*4,608),'#ffffff')
    for j,i in enumerate((24,49,89,131)):
        im=frame(entry['model'][i],i)
        ImageDraw.Draw(im).text((12,578),f'AI avatar / {i/30:.2f} s',fill='white')
        sheet.paste(im,(j*416,0))
    sheet.save(PRIVATE/'cpu_contact_sheet.jpg',quality=92)
    (HERE/'render_metrics.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
