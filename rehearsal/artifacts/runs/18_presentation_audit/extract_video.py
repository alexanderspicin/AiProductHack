"""Extract the already-embedded video for read-only review, without changing the deck."""
import argparse
from pathlib import Path
import zipfile

p = argparse.ArgumentParser()
p.add_argument("deck", type=Path)
p.add_argument("out", type=Path)
a = p.parse_args()
with zipfile.ZipFile(a.deck) as archive:
    info = archive.getinfo("ppt/media/media1.mp4")
    with archive.open(info) as source, a.out.open("xb") as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
    print(f"Extracted embedded video: {info.file_size} bytes")
