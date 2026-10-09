"""Write labelled raw ESP32-shaped fixtures; never opens a serial port or network."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neuratwin import bench_emulator


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=Path('reports/emulated-device.ndjson'))
    p.add_argument('--samples',type=int,default=241);args=p.parse_args()
    if not 1<=args.samples<=10000:p.error('Use 1–10000 samples.')
    state=bench_emulator.new();args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8') as out:
        for _ in range(args.samples):
            row=bench_emulator.step(state,training=True)
            frame={'type':'telemetry_raw','emulated':True,**{k:row[k] for k in ('device_id','boot_id','sequence','uptime_ms','relay_states','relay_output_configured','quality_flags')},**row['raw']}
            out.write(json.dumps(frame,allow_nan=False)+'\n')
    print(f'Wrote {args.samples} labelled emulator samples to {args.output}. Physical bridge rejects these fixtures.')


if __name__=='__main__':main()
