"""Verify local example URLs and decode existing video/audio; no generation/API."""
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
import numpy as np

BASE = 'http://127.0.0.1:8897'
CLIPS = ['new_training_cpu.mp4', 'new_closures_cpu.mp4', 'new_rounding_cpu.mp4', 'comparison.mp4']


def main():
    for attempt in range(60):
        try:
            with urlopen(BASE+'/manifest.json', timeout=2) as response:
                manifest = json.load(response)
            break
        except OSError:
            if attempt == 59: raise
            time.sleep(.5)
    with urlopen(BASE+'/', timeout=5) as response:
        assert response.status == 200
        assert 'Что произнести?' in response.read().decode()
    results = {'date': '2026-09-06', 'base': BASE, 'page_ready': True, 'poses': manifest['poses'], 'examples': []}
    for name in CLIPS:
        url = BASE+'/'+name
        with urlopen(url, timeout=5) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == 'video/mp4'
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', url]))
        kinds = {stream['codec_type'] for stream in info['streams']}
        assert {'video', 'audio'} <= kinds
        subprocess.run(['ffmpeg', '-v', 'error', '-i', url, '-map', '0:v:0', '-t', '1', '-f', 'null', '-'], check=True, capture_output=True)
        pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', url, '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'])
        samples = np.frombuffer(pcm, dtype='<f4')
        rms = float(np.sqrt(np.mean(samples*samples)))
        assert rms > .001, 'Audio is silent'
        results['examples'].append({'name': name, 'url': url, 'streams': info['streams'], 'duration_s': float(info['format']['duration']), 'audio_rms': rms, 'decoded': True})
    with urlopen(BASE+'/assets/atlas/000.png', timeout=5) as response:
        assert response.status == 200
    results['external_paid_calls'] = 0
    Path(__file__).with_name('launch_2026-09-06.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
