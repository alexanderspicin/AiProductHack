"""Staged, logged avatar build. Explicit GPU handoff; no credentials/cloud guessing."""
import argparse
from datetime import datetime, timezone
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

HERE=Path(__file__).resolve().parent
COMMIT='4a90da6e32b9cef7ed850455eddc754abed8b454'


def run(root,cmd,cwd=None):
    start=time.monotonic()
    result=subprocess.run([str(x) for x in cmd],cwd=cwd)
    record={'utc':datetime.now(timezone.utc).isoformat(),'command':[str(x) for x in cmd],'seconds':time.monotonic()-start,'returncode':result.returncode}
    root.mkdir(parents=True,exist_ok=True)
    with (root/'commands.jsonl').open('a') as log:log.write(json.dumps(record)+'\n')
    if result.returncode:raise RuntimeError('Stage failed; see commands.jsonl')


def copy(source,dest):
    dest.parent.mkdir(parents=True,exist_ok=True)
    if source.is_dir():shutil.copytree(source,dest,dirs_exist_ok=True)
    else:shutil.copy2(source,dest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['doctor','init-local','fetch','prepare','export-gpu','bake','import-baked','infer','serve','media','pack'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--python',default=sys.executable)
    p.add_argument('--from-root',type=Path);p.add_argument('--assets',type=Path)
    p.add_argument('--audio-dir',type=Path);p.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    p.add_argument('--poses',type=int,default=100);p.add_argument('--states',type=int,default=64)
    p.add_argument('--out',type=Path);p.add_argument('--input',type=Path);p.add_argument('--port',type=int,default=8897)
    p.add_argument('--smoke',action='store_true');p.add_argument('--legacy',action='store_true')
    args=p.parse_args();root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    stage=args.stage
    if stage=='doctor':
        result={'root_exists':True,'source_ready':(root/'teacher_source/talkingface/models/DINet_mini.py').is_file(),
          'weights_ready':(root/'teacher_weights/checkpoint/DINet_mini/epoch_40.pth').is_file(),
          'prepared':(root/'inputs/web_inputs.json').is_file(),'runtime_ready':(root/'package/atlas/000.png').is_file(),
          'commands':{x:bool(shutil.which(x)) for x in ['git','ffmpeg','node','say']},
          'modules':{x:bool(importlib.util.find_spec(x)) for x in ['numpy','PIL','onnxruntime','kaldi_native_fbank','torch','cv2']},
          'input_contract':'DH Live mini v1 assets/01.mp4 plus combined_data.json.gz; a photo alone is not a prepared avatar'}
        print(json.dumps(result,indent=2));return
    if stage=='init-local':
        if not args.from_root:p.error('--from-root required')
        if (root/'teacher_source').exists():p.error('Destination already has a source tree; choose a new root')
        source=args.from_root.resolve()
        if source==root:p.error('Source and destination must differ')
        for name in ['teacher_source','teacher_weights']:copy(source/name,root/name)
    elif stage=='fetch':
        if (root/'teacher_source').exists():p.error('Source already exists; choose a new root')
        repo=root/'upstream';run(root,['git','clone','--no-checkout','https://github.com/kleinlee/DH_live',repo])
        source=root/'teacher_source';source.mkdir()
        archive=root/'source.tar';run(root,['git','-C',repo,'archive','--output',archive,COMMIT])
        run(root,['tar','-xf',archive,'-C',source])
        hf=Path(args.python).resolve().parent/'hf'
        if not hf.is_file():
            found=shutil.which('hf')
            if not found:raise RuntimeError('Install huggingface_hub[cli] in preparation environment, then download the two documented weights')
            hf=Path(found)
        run(root,[hf,'download','ztj7728/DH_live','checkpoint/DINet_mini/epoch_40.pth','checkpoint/lstm/lstm_model_epoch_325.pkl','--local-dir',root/'teacher_weights'])
    elif stage=='prepare':
        cmd=[args.python,HERE/'prepare.py','--root',root,'--poses',args.poses,'--states',args.states]
        if args.assets:cmd+=['--assets',args.assets.resolve()]
        if args.audio_dir:cmd+=['--audio-dir',args.audio_dir.resolve()]
        run(root,cmd);run(root,['node',HERE/'prompts.mjs',root])
    elif stage=='export-gpu':
        if not args.out:p.error('--out required (new directory)')
        dest=args.out.resolve()
        if dest.exists():p.error('GPU job directory already exists; choose a new directory')
        required=['teacher_source/talkingface/models/DINet_mini.py','teacher_source/mini_live/face_fusion_mask.png','teacher_source/mini_live/mouth_fusion_mask.png',
                  'teacher_weights/checkpoint/DINet_mini/epoch_40.pth','inputs/source.npy','inputs/reference.npy','package/manifest.json']
        for name in required:copy(root/name,dest/name)
        if args.smoke:copy(root/'inputs/prompts/atlas_000.bin',dest/'inputs/prompts/atlas_000.bin')
        else:copy(root/'inputs/prompts',dest/'inputs/prompts')
        copy(HERE/'bake_gpu.py',dest/'bake_gpu.py')
        (dest/'RUN.txt').write_text('python bake_gpu.py --root .'+(' --smoke' if args.smoke else '')+'\nRequires CUDA PyTorch and opencv-python-headless. Return baked/ to import-baked.\n')
        print('GPU job prepared. Transfer this directory to your explicitly authorized GPU machine; run the command in RUN.txt.')
    elif stage=='bake':
        run(root,[args.python,HERE/'bake_gpu.py','--root',root,'--device',args.device]+(['--smoke'] if args.smoke else []))
    elif stage=='import-baked':
        if not args.input:p.error('--input baked directory required')
        source=args.input.resolve();meta=json.loads((root/'package/manifest.json').read_text());record=source/'bake_manifest.json'
        if record.exists():
            built=json.loads(record.read_text())
            if not meta.get('build_id') or built.get('build_id')!=meta['build_id']:raise ValueError('Different build_id: refuse mixing avatars')
        elif not args.legacy:raise ValueError('Missing bake manifest; --legacy is only for the documented old run07 package')
        from PIL import Image
        for i in range(meta['poses']):
            file=source/f'atlas/{i:03d}.png'
            with Image.open(file) as img:
                img.load()
                if img.size!=(1024,128*((meta['states']+7)//8)):raise ValueError('Invalid atlas dimensions')
        for i in range(meta['poses']):copy(source/f'atlas/{i:03d}.png',root/f'package/atlas/{i:03d}.png')
    elif stage=='infer':
        if not args.input or not args.out:p.error('--input PCM16 WAV and --out MP4 required')
        run(root,[args.python,HERE/'runtime.py','--package',root/'package','--wav',args.input.resolve(),'--out',args.out.resolve()])
    elif stage=='serve':run(root,[args.python,HERE/'lab.py','--root',root,'--port',args.port])
    elif stage=='media':run(root,[args.python,HERE/'prepare_media.py','--root',root])
    elif stage=='pack':
        if not args.out:p.error('--out archive.tar.gz required')
        if args.out.exists():p.error('Archive already exists; choose a new file')
        for name in ['runtime.py','audio_driver.py','requirements-cpu.txt','lab.py','index.html','motion.js','examples.html','media_http.py']:copy(HERE/name,root/'package'/name)
        copy(HERE/'PORTABLE.md',root/'package/README.md')
        with tarfile.open(args.out,'w:gz') as archive:
            archive.add(root/'package',arcname='package',filter=lambda info:None if '__pycache__' in info.name else info)
            for stem in ['comparison','new_training_cpu','new_closures_cpu','new_rounding_cpu']:
                for ext in ['webm','mp4']:
                    file=root/f'{stem}.{ext}'
                    if file.exists():archive.add(file,arcname=file.name)
            poster=root/'comparison_poster.jpg'
            if poster.exists():archive.add(poster,arcname=poster.name)
    print(f'{stage}: done')


if __name__=='__main__':main()
