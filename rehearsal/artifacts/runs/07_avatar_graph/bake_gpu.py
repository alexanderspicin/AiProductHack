"""Offline ONLY: turn pose x mouth controls into stored pixels (CUDA or CPU check)."""
import argparse
import importlib.util
import json
from pathlib import Path
import time
import numpy as np
import torch
from PIL import Image


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--smoke',action='store_true')
    p.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    args=p.parse_args();root=args.root.resolve()
    cuda=args.device=='cuda'
    if cuda and not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable; --device cpu allows a small offline check')
    torch.set_num_threads(4)
    spec=importlib.util.spec_from_file_location('teacher',root/'teacher_source/talkingface/models/DINet_mini.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    model=mod.DINet_mini_pipeline(3,12,cuda=cuda).to(args.device).eval()
    weights=torch.load(root/'teacher_weights/checkpoint/DINet_mini/epoch_40.pth',map_location='cpu',weights_only=True)
    model.infer_model.load_state_dict(weights['state_dict']['net_g'],strict=True)
    reference=torch.from_numpy(np.load(root/'inputs/reference.npy')).to(args.device)
    source=torch.from_numpy(np.load(root/'inputs/source.npy')).permute(0,3,1,2).float().to(args.device)/255
    config=json.loads((root/'package/manifest.json').read_text())
    output=root/'baked';output.mkdir(exist_ok=True)
    (output/'atlas').mkdir(exist_ok=True)
    (output/'bake_manifest.json').write_text(json.dumps({k:config.get(k) for k in ['format','build_id','poses','states','size']},indent=2))
    def infer(prompts,poses):
        result=[]
        batch_size=32 if cuda else 1  # upstream CPU AdaAT fixes its batch dimension to one
        for i in range(0,len(poses),batch_size):
            selected=poses[i:i+batch_size]
            gl=torch.from_numpy(prompts[i:i+batch_size].copy()).permute(0,3,1,2).float().to(args.device)/255
            model.infer_model.ref_in_feature=reference.repeat(len(selected),1,1,1)
            with torch.inference_mode():
                pixels=model.interface(source[selected].clone(),gl)[:,:3]
            result.append((pixels.permute(0,2,3,1).clamp(0,1)*255).round().byte().cpu().numpy())
        return np.concatenate(result)
    start=time.perf_counter();frames=0
    for pose in range(1 if args.smoke else config['poses']):
        prompts=np.fromfile(root/f'inputs/prompts/atlas_{pose:03d}.bin',np.uint8).reshape(-1,128,128,4)
        if len(prompts)!=config['states']:
            raise ValueError('Prompt count does not match manifest; rerun prompts.mjs')
        images=infer(prompts,[pose]*len(prompts))
        # Lossless PNG tile sheet. Runtime only decodes stored pixels.
        cols=8;rows=(len(images)+cols-1)//cols
        sheet=np.zeros((rows*128,cols*128,3),np.uint8)
        for k,img in enumerate(images):sheet[k//cols*128:(k//cols+1)*128,k%cols*128:(k%cols+1)*128]=img
        Image.fromarray(sheet).save(output/'atlas'/f'{pose:03d}.png',compress_level=3)
        frames+=len(images)
        if pose%10==0:print(json.dumps({'pose':pose,'seconds':time.perf_counter()-start}),flush=True)
    if not args.smoke:
        n=config['poses']
        for name,clip in config['heldout'].items():
            prompts=np.fromfile(root/f'inputs/prompts/{name}.bin',np.uint8).reshape(-1,128,128,4)
            phases=np.arange(len(prompts))%max(1,2*n-2)
            phases=np.where(phases<n,phases,2*n-2-phases).tolist()
            images=infer(prompts,phases)
            np.save(output/f'{name}_teacher.npy',images)
            frames+=len(images)
    if cuda:torch.cuda.synchronize()
    metrics={'device':args.device,'gpu':torch.cuda.get_device_name() if cuda else None,'frames':frames,'seconds':time.perf_counter()-start,
             'peak_allocated_mb':torch.cuda.max_memory_allocated()/1e6 if cuda else None,'torch':torch.__version__,'strict_weights':True,
             'image_net_only_offline':True,'smoke':args.smoke}
    (output/('smoke_metrics.json' if args.smoke else 'bake_metrics.json')).write_text(json.dumps(metrics,indent=2))
    print(json.dumps(metrics),flush=True)


if __name__=='__main__':main()
