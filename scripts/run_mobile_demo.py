"""Run the shared demo API on the LAN for the Expo app and web client."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.chdir(ROOT)

if __name__=='__main__':
    from dotenv import load_dotenv
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,help='Backend environment file; defaults to ../env when present')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--push',action='store_true',help='Enable delivery to devices explicitly registered by the user')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env')
    source=args.env_file or (ROOT.parent/'env' if (ROOT.parent/'env').is_file() else None)
    if source:
        if not source.is_file(): parser.error('The specified environment file does not exist.')
        load_dotenv(source,override=True)
    os.environ.setdefault('HALO_STORAGE_BACKEND','sqlite')
    os.environ.setdefault('NEURATWIN_DB',str(ROOT/'runtime'/'standalone-rehearsal.sqlite3'))
    os.environ['HALO_ALLOW_CONTROL']='0'
    os.environ['HALO_MOBILE_DEMO']='1'
    os.environ['HALO_SERVER_CLOCK']='1'
    os.environ['HALO_PUSH_ENABLED']='1' if args.push else '0'
    os.environ['HALO_OPERATOR_TOKEN']=os.getenv('HALO_OPERATOR_TOKEN') or secrets.token_urlsafe(24)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as connection:
        try:
            connection.connect(('8.8.8.8',80))
            address=connection.getsockname()[0]
        except OSError:
            address=socket.gethostbyname(socket.gethostname())
    mobile_url=os.getenv('HALO_MOBILE_PUBLIC_URL') or f'http://{address}:{args.port}'
    config=ROOT/'mobile'/'.env.local'
    lines=config.read_text().splitlines() if config.exists() else []
    lines=[line for line in lines if not line.startswith('EXPO_PUBLIC_API_URL=')]
    config.write_text('\n'.join(lines+[f'EXPO_PUBLIC_API_URL={mobile_url}'])+'\n')
    generated=ROOT/'mobile'/'src'/'generated'
    generated.mkdir(parents=True,exist_ok=True)
    (generated/'connection.json').write_text(json.dumps({'url':mobile_url}))
    print(f"Hackathon app configured with {os.environ['HALO_STORAGE_BACKEND']} storage.",flush=True)
    import uvicorn
    uvicorn.run('neuratwin.app:app',host=args.host,port=args.port)
