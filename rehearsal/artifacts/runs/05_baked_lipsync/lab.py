"""Isolated local lip-sync experiment. No credentials, uploads or Pipecat changes.

Audio-to-three-axis projection adapted from EMMA Skin (Apache-2.0, Ryan Chen).
Model: myned-ai/wav2arkit_cpu, wav2vec2 + LAM. Explicit CPU execution only.
"""
from __future__ import annotations

import argparse
import base64
import json
import platform
import subprocess
import tempfile
import threading
import time
import wave
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import onnxruntime as ort

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parents[1] / 'private' / '05_baked_lipsync'
PHRASES = [
    ('calibration', 'Аня, Оля, Ира, Уля. Мама, папа, бабушка. Федя, Вера. Мы обсуждаем проект спокойно и внимательно.'),
    ('closures', 'Папа купил бумагу. Мама помогла мне подготовить подробный план.'),
    ('rounding', 'У Юли уютный дом. У Оли новый ноутбук. Ирина ищет решение.'),
    ('training', 'Я понимаю ваше недовольство. Давайте уточним, что произошло, и вместе найдём решение.'),
]


def synthesize(text: str) -> tuple[bytes, np.ndarray, float]:
    """Local macOS voice. Passing input over stdin prevents command/option injection."""
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise ValueError('Нужен текст от 1 до 500 символов')
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='lipsync-say-') as folder:
        raw, wav = Path(folder) / 'speech.aiff', Path(folder) / 'speech.wav'
        subprocess.run(['say', '-v', 'Milena', '-r', '175', '-o', str(raw)],
                       input=text, text=True, check=True, capture_output=True, timeout=35)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(raw), '-ar', '16000',
                        '-ac', '1', '-c:a', 'pcm_s16le', str(wav)],
                       check=True, capture_output=True, timeout=20)
        with wave.open(str(wav)) as f:
            pcm = np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype(np.float32) / 32768
        return wav.read_bytes(), pcm, (time.perf_counter() - t0) * 1000


class Driver:
    def __init__(self):
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        t0 = time.perf_counter()
        self.session = ort.InferenceSession(str(PRIVATE / 'model/wav2arkit_cpu.onnx'), so,
                                            providers=['CPUExecutionProvider'])
        self.load_ms = (time.perf_counter() - t0) * 1000
        self.names = json.loads((PRIVATE / 'model/config.json').read_text())['blendshape_names']
        self.calibration = json.loads((PRIVATE / 'calibration.json').read_text()) if (PRIVATE / 'calibration.json').exists() else None

    def infer(self, pcm):
        t0 = time.perf_counter()
        bs = self.session.run(None, {'audio_waveform': pcm[None, :].astype(np.float32)})[0][0]
        assert np.isfinite(bs).all(), 'nonfinite model result'
        return bs, (time.perf_counter() - t0) * 1000

    def axes(self, bs):
        def c(name):
            return bs[:, self.names.index(name)]
        return np.column_stack([
            c('jawOpen') + .5 * c('mouthLowerDownLeft') + .5 * c('mouthLowerDownRight') - c('mouthClose'),
            .5 * (c('mouthStretchLeft') + c('mouthStretchRight') + c('mouthSmileLeft') + c('mouthSmileRight')),
            .5 * (c('mouthPucker') + c('mouthFunnel')),
        ])

    def curves(self, pcm, bs):
        axes = self.axes(bs)
        lo, hi = np.array(self.calibration['lo']), np.array(self.calibration['hi'])
        norm = np.clip((axes - lo) / np.maximum(hi - lo, .001), 0, 1)
        # Shared projection for both variants; no test-phrase parameter tuning.
        norm[:, 0] = .55 * norm[:, 0] ** 2
        energy = np.array([np.sqrt(np.mean(pcm[int(i*len(pcm)/len(bs)):max(int((i+1)*len(pcm)/len(bs)),int(i*len(pcm)/len(bs))+1)] ** 2)) for i in range(len(bs))])
        loudness = np.column_stack([.55 * np.clip(energy / self.calibration['rms_p99'], 0, 1) ** 2,
                                   np.full(len(bs), .3), np.full(len(bs), .2)])
        # Close in real audio silence, not from transcript guesses. Same gate for both.
        silent = energy < .006
        norm[silent] = [0, .3, .2]
        loudness[silent] = [0, .3, .2]
        return norm.round(5).tolist(), loudness.round(5).tolist()


def prepare():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    d = Driver()
    metrics = {'hardware': platform.platform(), 'chip': subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip(),
               'onnxruntime': ort.__version__, 'providers': d.session.get_providers(), 'threads': 4,
               'model_load_ms': round(d.load_ms, 2), 'model_bytes': sum(p.stat().st_size for p in (PRIVATE/'model').glob('*.onnx*')),
               'phrases': [], 'api_spend_rub': 0, 'gpu_pod_used': False, 'quality_scores': None}
    manifest = []
    samples = {}
    for name, text in PHRASES:
        wav, pcm, say_ms = synthesize(text)
        samples[name] = pcm
        (PRIVATE / f'{name}.wav').write_bytes(wav)
        bs, cold_ms = d.infer(pcm)
        if name == 'calibration':
            axes = d.axes(bs)
            rms = [np.sqrt(np.mean(part**2)) for part in np.array_split(pcm, len(bs))]
            d.calibration = {'lo': np.percentile(axes, 5, axis=0).tolist(), 'hi': np.percentile(axes, 99, axis=0).tolist(),
                             'rms_p99': float(np.percentile(rms, 99)), 'phrase': text,
                             'openness_gain': .55, 'openness_gamma': 2, 'silence_rms': .006}
            (PRIVATE / 'calibration.json').write_text(json.dumps(d.calibration, ensure_ascii=False, indent=2))
            continue
        times = [d.infer(pcm)[1] for _ in range(3)]
        model, energy = d.curves(pcm, bs)
        duration = len(pcm) / 16000
        entry = {'id': name, 'text': text, 'duration_s': duration, 'fps': len(bs) / duration,
                 'nominal_fps': 30, 'model': model, 'energy': energy, 'audio': f'/data/{name}.wav'}
        (PRIVATE / f'{name}.json').write_text(json.dumps(entry, ensure_ascii=False))
        manifest.append({k: entry[k] for k in ('id', 'text', 'duration_s', 'audio')})
        metrics['phrases'].append({'id': name, 'duration_s': duration, 'frames': len(bs), 'tts_ms': round(say_ms, 2),
                                  'initial_inference_ms': round(cold_ms, 2), 'warm_inference_ms': times,
                                  'median_inference_ms': float(np.median(times)), 'rtf_compute_over_audio': float(np.median(times)/1000/duration),
                                  'frame_timeline_error_ms': round((len(bs)/30-duration)*1000, 2)})
    # Chunking is a separate diagnostic: compare identical interior samples to full-context output.
    pcm = samples['training']
    full, _ = d.infer(pcm)
    metrics['chunks'] = []
    for seconds in (1, 2):
        segment = pcm[16000:16000 + seconds*16000]
        part, ms = d.infer(segment)
        aligned = full[30:30 + len(part)]
        metrics['chunks'].append({'audio_s': seconds, 'inference_ms': ms,
                                  'extra_wait_if_full_chunk_required_ms': seconds*1000,
                                  'mean_abs_coefficient_difference_from_full_context': float(np.abs(aligned-part).mean())})
    (PRIVATE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (HERE / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


class Handler(SimpleHTTPRequestHandler):
    driver = None
    lock = threading.Lock()

    def translate_path(self, path):
        path = unquote(urlparse(path).path)
        root, suffix = (PRIVATE, path[6:]) if path.startswith('/data/') else (HERE, path.lstrip('/') or 'index.html')
        candidate = (root / suffix).resolve()
        if not candidate.is_relative_to(root.resolve()):
            return str(HERE / '__not_found__')
        return str(candidate)

    def do_POST(self):
        # Reject browser-origin cross-site requests; loopback binding alone is insufficient.
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
            return self.send_error(403)
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.send_error(403)
        if self.path != '/synthesize':
            return self.send_error(404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send_error(400)
        if length <= 0 or length > 8192:
            return self.send_error(413)
        if not self.lock.acquire(blocking=False):
            return self.send_error(429, 'One synthesis at a time')
        try:
            text = json.loads(self.rfile.read(length))['text']
            wav, pcm, tts_ms = synthesize(text)
            bs, infer_ms = self.driver.infer(pcm)
            model, energy = self.driver.curves(pcm, bs)
            payload = {'text': text, 'wav_base64': base64.b64encode(wav).decode(), 'duration_s': len(pcm)/16000,
                       'fps': len(bs)/(len(pcm)/16000), 'model': model, 'energy': energy,
                       'tts_ms': tts_ms, 'infer_ms': infer_ms}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, KeyError):
            self.send_error(400, 'Invalid text')
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browser invalidates cancelled generations; there is no paid work.
        except Exception as e:
            print(type(e).__name__, str(e), flush=True)
            self.send_error(500, 'Local synthesis failed')
        finally:
            self.lock.release()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['prepare', 'serve'])
    p.add_argument('--port', type=int, default=8896)
    args = p.parse_args()
    if args.command == 'prepare':
        prepare()
    else:
        Handler.driver = Driver()
        print(f'Local experiment: http://127.0.0.1:{args.port}', flush=True)
        ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
