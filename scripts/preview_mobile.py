"""Local browser preview of the Expo export, with a same-origin API proxy."""
import argparse
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, Response
import uvicorn

ROOT=Path(__file__).resolve().parents[1]/'mobile'/'dist'
app=FastAPI(docs_url=None,redoc_url=None)
backend='http://127.0.0.1:8765'

@app.api_route('/api/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
async def proxy(path:str,request:Request):
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Preview requests must come from this origin.')
    headers={k:v for k,v in request.headers.items() if k.lower() in ('authorization','content-type')}
    async with httpx.AsyncClient(timeout=40) as client:
        r=await client.request(request.method,backend+'/api/'+path,params=request.query_params,content=await request.body(),headers=headers)
    return Response(r.content,status_code=r.status_code,headers={'content-type':r.headers.get('content-type','application/json'),'cache-control':'no-store'})

@app.get('/{path:path}')
def page(path:str):
    file=(ROOT/path).resolve()
    if not file.is_relative_to(ROOT.resolve()):raise HTTPException(404)
    return FileResponse(file if file.is_file() else ROOT/'index.html',headers={'Cache-Control':'no-store'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8082)
    parser.add_argument('--api-port',type=int,default=8765)
    args=parser.parse_args()
    backend=f'http://127.0.0.1:{args.api_port}'
    uvicorn.run(app,host='127.0.0.1',port=args.port)
