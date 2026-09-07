"""Create browser-compatible derivatives; original MP4s remain unchanged."""
import argparse
from pathlib import Path
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args()
    for name in ['comparison','new_training_cpu','new_closures_cpu','new_rounding_cpu']:
        source=args.root/f'{name}.mp4';dest=args.root/f'{name}.webm'
        if not source.exists():continue
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-c:v','libvpx-vp9','-crf','30','-b:v','0','-row-mt','1','-c:a','libopus','-ar','48000',str(dest)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(args.root/'comparison.mp4'),'-frames:v','1',str(args.root/'comparison_poster.jpg')],check=True)


if __name__=='__main__':main()
