"""Explicit standalone SQLite rehearsal, with physical control disabled."""
from pathlib import Path
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
os.environ['HALO_STORAGE_BACKEND']='sqlite'
os.environ['NEURATWIN_DB']=str(ROOT/'runtime'/'standalone-rehearsal.sqlite3')
os.environ['HALO_LOCAL_OPERATOR']='1'
os.environ['HALO_ALLOW_CONTROL']='0'
os.environ['HALO_AI_ENABLED']='0'
os.environ.pop('HALO_OPERATOR_TOKEN',None)
os.environ.pop('HALO_DEVICE_TOKEN',None)

if __name__=='__main__':
    import uvicorn
    print('Standalone rehearsal: SQLite, loopback only, hardware control disabled.')
    uvicorn.run('neuratwin.app:app',host='127.0.0.1',port=8765)
