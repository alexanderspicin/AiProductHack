"""Extract and run the portable CPU package in a fresh temporary directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--wav',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='avatar-package-') as tmp:
        dest=Path(tmp)
        with tarfile.open(args.archive) as archive:archive.extractall(dest,filter='data')
        package=dest/'package'
        for name in ['index.html','motion.js','lab.py','media_http.py','audio_driver.onnx','manifest.json']:
            assert (package/name).is_file(),name
        res=subprocess.run([sys.executable,str(package/'runtime.py'),'--package',str(package),'--wav',str(args.wav.resolve()),'--out',str(dest/'test.mp4')],capture_output=True,text=True,check=True)
        metrics=json.loads(res.stdout)
        assert metrics['frames']>100 and (dest/'test.mp4').stat().st_size>1000
        result={'fresh_extraction':True,'ui_included':True,'runtime_subprocess':True,'runtime':metrics,'archive_bytes':args.archive.stat().st_size}
        args.out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
