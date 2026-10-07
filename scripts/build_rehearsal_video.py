"""Create a silent 60-second walkthrough from the five verified browser captures.

Capture each halo-fallback.html screen to reports/demo-frames/01.png ... 05.png.
Requires ffmpeg on PATH. This is a screenshot walkthrough, not hardware footage.
"""
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
frames=ROOT/'reports'/'demo-frames'
inputs=[frames/f'{i:02}.png' for i in range(1,6)]
if not all(p.is_file() for p in inputs):raise SystemExit('Capture all five fallback screens first.')
ffmpeg=shutil.which('ffmpeg')
if not ffmpeg:raise SystemExit('ffmpeg is required.')
playlist=frames/'sequence.txt'
playlist.write_text(''.join(f"file '{p.name}'\nduration 12\n" for p in inputs)+f"file '{inputs[-1].name}'\n",encoding='utf-8')
subprocess.run([ffmpeg,'-y','-loglevel','warning','-f','concat','-safe','0','-i',str(playlist),
                '-vf','scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xf4f3ee,setsar=1',
                '-r','24','-t','60','-c:v','libx264','-preset','medium','-crf','19','-pix_fmt','yuv420p',
                '-movflags','+faststart','-an','-metadata','title=NeuraTwin Halo - precomputed synthetic software walkthrough',
                '-metadata','comment=Silent screenshot walkthrough. Not live acquisition or hardware footage.',
                str(ROOT/'web'/'halo-rehearsal.mp4')],check=True)
print('Created web/halo-rehearsal.mp4: 60 seconds, labelled synthetic software walkthrough.')
