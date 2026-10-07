"""Protect all cloud application routes, including the older distribution API."""
import re
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from . import cloud, auth


class CloudMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        if not cloud.enabled(): return await call_next(request)
        unit=cloud.UnitOfWork(); token=cloud.current.set(unit)
        try:
            path=request.url.path
            if path.startswith('/api/'):
                if request.method not in ('GET','HEAD','OPTIONS'): auth.csrf(request)
                public=path in ('/api/health','/api/auth/config','/api/auth/login','/api/auth/refresh','/api/auth/logout','/api/halo/session')
                device=path=='/api/halo/telemetry' or path.startswith('/api/halo/device/')
                judge=bool(re.fullmatch(r'/api/halo/arena/rooms/[^/]+/(judge|inject)',path))
                if not (public or device or judge):
                    role='viewer' if request.method in ('GET','HEAD') else 'operator'
                    if path in ('/api/halo/config','/api/halo/calibrations') and request.method not in ('GET','HEAD'):role='admin'
                    await run_in_threadpool(auth.identity,request,role)
            response=await call_next(request)
            if response.status_code<400:
                if unit.writes:
                    user=getattr(request.state,'halo_identity',{})
                    unit.event('WORKSPACE','request_committed',{'actor':user.get('user_id','device or scoped capability'),
                               'method':request.method,'path':path,'records':[{'kind':k,'id':i} for k,i in unit.writes]})
                await run_in_threadpool(unit.commit)
            if path.startswith('/api/'):
                response.headers['Cache-Control']='no-store'
                response.headers['X-Content-Type-Options']='nosniff'
            return response
        except HTTPException as error:
            return JSONResponse({'detail':error.detail},status_code=error.status_code,headers={'Cache-Control':'no-store'})
        finally:
            cloud.current.reset(token)
