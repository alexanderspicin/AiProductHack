"""Prepare calibration controls and teacher inputs; never use held-out speech to fit."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import uuid
import numpy as np
from PIL import Image

CALIBRATION = [
    "Мама попросила Павла купить молоко, бананы и мягкий белый хлеб.",
    "Утром Юлия увидела утку у озера. Около воды очень уютно и спокойно.",
    "Фёдор внимательно выслушал ваше возражение. Вы вправе выбрать другой вариант.",
    "Сейчас расскажу, зачем нужна эта инструкция и как проверить каждый шаг.",
    "Шесть рыжих мышей тихо шуршали, а чёрный кот ждал за дверью.",
    "Привет! Как настроение? Давайте вместе решим сложную задачу. Всё получится.",
    "Тридцать три рубля, пять копеек. Пожалуйста, повторите номер заказа.",
    "А, о, у, э, и, ы. Па, ба, ма. Фа, ва. Шу, чу, жу. Ли, ри, ти, ди.",
]
HELDOUT = {
    "new_training": "Здравствуйте! Представьте, что клиент сердится из-за задержки доставки. Как вы начнёте разговор?",
    "new_closures": "Борис, мы можем перенести встречу на понедельник. Вам будет удобно в половине пятого?",
    "new_rounding": "У Ольги новая уютная студия. Её жёлтый щенок уже уснул около кресла. Хорошего вечера!",
}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def speech(text, dest):
    if dest.exists():
        return
    subprocess.run(["say", "-v", "Milena", "-r", "165", "-o", str(dest.with_suffix('.aiff')), text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(dest.with_suffix('.aiff')), "-af", "apad=pad_dur=0.4", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dest)], check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--poses", type=int, default=100)
    p.add_argument("--states", type=int, default=64)
    p.add_argument("--assets", type=Path, help="Prepared DH Live mini v1 assets: 01.mp4 and combined_data.json.gz")
    p.add_argument("--width", type=int, default=360)
    p.add_argument("--audio-dir", type=Path, help="Reuse recorded calibration_0..7.wav and new_*.wav instead of macOS say")
    args = p.parse_args()
    root = args.root.resolve()
    source = root/'teacher_source'
    assets = args.assets.resolve() if args.assets else source/'web_demo/static/assets'
    data = json.load(gzip.open(assets/'combined_data.json.gz'))
    if len(data.get('ref_data',[])) != 6480:
        raise ValueError('Expected DH Live mini v1 reference (6480 floats), not mini2.0')
    if not 2<=args.states<=256 or not 1<=args.poses<=len(data['json_data']):
        raise ValueError('Invalid state/pose count for these assets')
    if not 128<=args.width<=1920:raise ValueError('Width must be 128..1920')
    inputs, package = root/'inputs', root/'package'
    inputs.mkdir(exist_ok=True)
    package.mkdir(exist_ok=True)
    (package/'base').mkdir(exist_ok=True)
    if (package/'atlas').exists():raise ValueError('Choose a fresh build root; an existing baked avatar must not be overwritten')
    if args.audio_dir:
        for name in [f'calibration_{i}' for i in range(len(CALIBRATION))]+list(HELDOUT):
            source_wav=args.audio_dir.resolve()/f'{name}.wav'
            if source_wav.resolve()!=(inputs/f'{name}.wav').resolve():shutil.copy2(source_wav,inputs/f'{name}.wav')
    import torch
    torch.set_num_threads(2)
    torch.manual_seed(20260905)
    mod = load_module(source/'talkingface/models/audio2bs_lstm.py', 'upstream_audio')
    model = mod.Audio2Feature().eval()
    state = torch.load(root/'teacher_weights/checkpoint/lstm/lstm_model_epoch_325.pkl', map_location='cpu', weights_only=True)
    model.load_state_dict(state, strict=True)
    audio = torch.zeros(1, 40, 80)
    hc = torch.zeros(2, 1, 192)
    torch.onnx.export(model, (audio, hc, hc), str(package/'audio_driver.onnx'),
                      input_names=['audio', 'h', 'c'], output_names=['bs', 'hn', 'cn'],
                      opset_version=17, dynamo=False)
    from audio_driver import Driver
    driver = Driver(package/'audio_driver.onnx')
    with torch.no_grad():
        x = torch.randn(1,40,80)
        expected = model(x,hc,hc)[0].numpy()[0]
    onnx_error = float(np.max(np.abs(expected-driver.infer_features(x.numpy()[0]))))
    trajectories = []
    for i, text in enumerate(CALIBRATION):
        dest = inputs/f'calibration_{i}.wav'
        speech(text,dest)
        bs, silent, timing = driver.wav(dest)
        if timing['duration_s']<1 or silent.all():
            raise ValueError(f'{dest.name}: no calibration speech. macOS say may be sandboxed; supply recorded WAVs with --audio-dir')
        trajectories.append(bs)
    controls = np.concatenate(trajectories)
    # Freeze scale and codebook using calibration only. Farthest-point medoids retain
    # actually observed states; deterministic Lloyd updates choose observed medoids.
    scale = np.maximum(controls.std(0), 0.1)
    z = controls/scale
    centres = [np.zeros(6, np.float32)]
    for _ in range(args.states-1):
        distances = ((z[:,None]-np.array(centres)[None])**2).sum(2).min(1)
        centres.append(z[distances.argmax()])
    centres = np.array(centres)
    for _ in range(8):
        assignment = ((z[:,None]-centres[None])**2).sum(2).argmin(1)
        for k in range(1,args.states):
            pts = z[assignment==k]
            if len(pts):
                centres[k] = pts[((pts-pts.mean(0))**2).sum(1).argmin()]
    codebook = centres*scale
    calibration_dist = ((z[:,None]-centres[None])**2).sum(2).min(1)
    coverage = float(np.quantile(calibration_dist, .99)*1.5)
    np.save(inputs/'codebook.npy',codebook)
    np.save(inputs/'scale.npy',scale)
    # Held-out inference begins only after codebook, scale and coverage are frozen.
    evaluation = {}
    for name,text in HELDOUT.items():
        dest = inputs/f'{name}.wav'
        speech(text,dest)
        bs,silent,timing=driver.wav(dest)
        np.save(inputs/f'{name}.npy',bs)
        evaluation[name] = {'text':text, 'frames':len(bs), 'timing':timing}
    count = min(args.poses,len(data['json_data']))
    # Public demo: identity/weight rights are not cleared for commercial use here.
    import cv2
    video=cv2.VideoCapture(str(assets/'01.mp4'))
    original_width=int(video.get(cv2.CAP_PROP_FRAME_WIDTH));original_height=int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not original_width or not original_height:raise ValueError('Cannot decode source video')
    output_width=args.width//2*2;output_height=round(original_height/original_width*output_width/2)*2
    sx=output_width/original_width;sy=output_height/original_height
    crops=[]; rects=[]
    for i in range(count):
        ok,frame=video.read()
        if not ok: raise RuntimeError('Source video shorter than metadata')
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        rect=data['json_data'][i]['rect']
        x1,y1,x2,y2=rect
        crops.append(np.asarray(Image.fromarray(rgb[y1:y2,x1:x2]).resize((128,128),Image.Resampling.BILINEAR).convert('RGBA')))
        small=Image.fromarray(rgb).resize((output_width,output_height),Image.Resampling.LANCZOS)
        small.save(package/'base'/f'{i:03d}.jpg',quality=94)
        rects.append([rect[0]*sx,rect[1]*sy,rect[2]*sx,rect[3]*sy])
    video.release()
    np.save(inputs/'source.npy',np.stack(crops))
    np.save(inputs/'reference.npy',np.array(data['ref_data'],np.float32).reshape(1,20,18,18))
    web={'face3D_obj':data['face3D_obj'],'poses':data['json_data'][:count], 'codebook':codebook.tolist(), 'heldout':{n:np.load(inputs/f'{n}.npy').tolist() for n in HELDOUT}}
    (inputs/'web_inputs.json').write_text(json.dumps(web))
    metadata={'format':'avatar-graph-1','build_id':uuid.uuid4().hex,'fps':25,'poses':count,'states':args.states,'size':[output_width,output_height], 'tile':128,'rects':rects,
              'codebook':codebook.tolist(),'scale':scale.tolist(),'coverage_threshold':coverage,
              'transition_weight':0.10,'lookahead_frames':2,'silence_state':0,
              'source':'https://github.com/kleinlee/DH_live/tree/4a90da6e32b9cef7ed850455eddc754abed8b454',
              'research_only':True,'watermark':'DH Live demo · AI · research',
              'training_sentences':CALIBRATION,'heldout':evaluation, 'onnx_max_abs_error':onnx_error}
    (package/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    print(json.dumps({'poses':count,'states':args.states,'calibration_frames':len(controls),'onnx_max_abs_error':onnx_error,'bs_range':[controls.min(0).tolist(),controls.max(0).tolist()]},indent=2))


if __name__=='__main__': main()
