"""Small CPU-only speech driver. Image generation is deliberately absent."""
from pathlib import Path
import time
import numpy as np
import onnxruntime as ort
import kaldi_native_fbank as knf
from scipy.io import wavfile
from scipy.signal import resample_poly


def features(path):
    sr, pcm = wavfile.read(path)
    if pcm.dtype != np.int16 or pcm.ndim != 1:
        raise ValueError("Expected mono signed PCM16 WAV")
    audio = pcm.astype(np.float32) / 32768
    audio = resample_poly(audio, 8000, sr)
    opts = knf.FbankOptions()
    opts.frame_opts.samp_freq = 8000
    opts.frame_opts.dither = 0
    opts.frame_opts.frame_length_ms = 50
    opts.frame_opts.frame_shift_ms = 20
    opts.frame_opts.snip_edges = False
    opts.mel_opts.num_bins = 80
    bank = knf.OnlineFbank(opts)
    bank.accept_waveform(8000, audio.tolist())
    bank.input_finished()
    f = np.array([bank.get_frame(i) for i in range(bank.num_frames_ready)], np.float32)
    return f, pcm, sr


class Driver:
    def __init__(self, path):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])

    def infer_features(self, f):
        # Fixed 0.8s tensor, recurrent state preserved between chunks. Not an image net.
        h = np.zeros((2, 1, 192), np.float32)
        c = h.copy()
        out = []
        for i in range(0, len(f), 40):
            chunk = f[i:i+40]
            actual = len(chunk)
            chunk = np.pad(chunk, ((0, 40-actual), (0, 0)), mode="edge")
            pred, h, c = self.session.run(None, {"audio": chunk[None], "h": h, "c": c})
            out.append(pred[0, : (actual+1)//2])
        return np.concatenate(out)

    def wav(self, path):
        start = time.perf_counter()
        f, pcm, sr = features(path)
        pred = self.infer_features(f)
        # Match upstream audio-to-graphics calibration. Discard its 200ms startup lag.
        count = max(1, int(np.ceil(len(pcm) / sr * 25)))
        pred = np.pad(pred, ((0, 6), (0, 0)), mode="edge")[5:5+count] * 0.5
        pred[:, 1] *= 0.8
        # Explicit silence override, including padded tail. RMS is not a speech VAD.
        silent = []
        for i in range(count):
            a = pcm[round(i*sr/25):round((i+1)*sr/25)].astype(np.float32)/32768
            silent.append(not len(a) or float(np.sqrt(np.mean(a*a))) < 0.003)
        pred[np.array(silent)] = 0
        return pred.astype(np.float32), np.array(silent), {"seconds": time.perf_counter()-start, "duration_s": len(pcm)/sr}
