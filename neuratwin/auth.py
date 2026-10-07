"""Supabase user sessions. Tokens stay in HttpOnly cookies, roles stay in DB."""
from functools import lru_cache
import hmac
import os
import uuid
from urllib.parse import urlparse
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from . import cloud

router=APIRouter(prefix='/api/auth')
ROLES={'viewer':0,'operator':1,'admin':2}
ACCESS='halo_access'; REFRESH='halo_refresh'
LOCAL='halo_local'


def csrf(request):
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Cross-origin writes are not allowed.')
    if request.headers.get('sec-fetch-site')=='cross-site':
        raise HTTPException(403,'Cross-site writes are not allowed.')


@lru_cache(maxsize=4)
def jwks(url):
    return jwt.PyJWKClient(url,cache_jwk_set=True,lifespan=300,timeout=5)


def claims(token):
    url,_=cloud.settings()
    endpoint=os.getenv('SUPABASE_JWKS_URL') or url+'/auth/v1/.well-known/jwks.json'
    if endpoint != url+'/auth/v1/.well-known/jwks.json':
        raise HTTPException(503,'Auth signing-key endpoint must belong to the configured Supabase project.')
    try:
        signing=jwks(endpoint).get_signing_key_from_jwt(token)
        value=jwt.decode(token,signing.key,algorithms=['ES256','RS256'],audience='authenticated',issuer=url+'/auth/v1',
                         options={'require':['exp','iat','sub','iss','aud']},leeway=5)
        uuid.UUID(value['sub'])
        return value
    except (jwt.PyJWTError,ValueError,KeyError):
        raise HTTPException(401,'Session expired or invalid. Sign in again.') from None


def identity(request,required='viewer'):
    cached=getattr(request.state,'halo_identity',None)
    if cached:
        if ROLES[cached['role']] < ROLES[required]: raise HTTPException(403,'This action requires '+required+' access.')
        return cached
    from .halo_api import LOCAL_TOKEN, local_request
    supplied=request.headers.get('authorization','').removeprefix('Bearer ').strip()
    if not supplied and not request.cookies.get(ACCESS):
        supplied=request.cookies.get(LOCAL,'')
    expected=os.getenv('HALO_OPERATOR_TOKEN')
    # The development owner credential is issued only to same-origin loopback.
    if supplied and ((expected and hmac.compare_digest(supplied,expected)) or
        (not expected and os.getenv('HALO_LOCAL_OPERATOR','0')=='1' and local_request(request) and hmac.compare_digest(supplied,LOCAL_TOKEN))):
        value={'user_id':'local-owner','email':None,'role':'admin','mode':'local operator'}
    else:
        token=supplied or request.cookies.get(ACCESS)
        if not token: raise HTTPException(401,'Team sign-in required.')
        decoded=claims(token)
        members=cloud.rows('halo_members',{'user_id':'eq.'+decoded['sub'],'active':'eq.true','select':'role'},1)
        if not members: raise HTTPException(403,'Your account has no active NeuraTwin team membership.')
        value={'user_id':decoded['sub'],'email':decoded.get('email'),'role':members[0]['role'],'mode':'supabase'}
    if ROLES[value['role']] < ROLES[required]: raise HTTPException(403,'This action requires '+required+' access.')
    request.state.halo_identity=value
    return value


def cookies(response,request,result):
    secure=request.url.scheme=='https' or request.url.hostname not in ('localhost','127.0.0.1','::1','testserver')
    response.set_cookie(ACCESS,result['access_token'],httponly=True,secure=secure,samesite='strict',max_age=int(result.get('expires_in',3600)),path='/api')
    response.set_cookie(REFRESH,result['refresh_token'],httponly=True,secure=secure,samesite='strict',max_age=604800,path='/api/auth')
    response.headers['Cache-Control']='no-store'


class Login(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=1,max_length=512)


@router.get('/config')
def config():
    return {'enabled':cloud.enabled(),'backend':'supabase' if cloud.enabled() else 'sqlite','registration':'administrator managed'}


@router.post('/login')
def login(payload:Login,request:Request,response:Response):
    csrf(request)
    if not cloud.enabled(): raise HTTPException(409,'Cloud sign-in is not enabled in SQLite mode.')
    result=cloud.request('POST','/auth/v1/token',params={'grant_type':'password'},payload=payload.model_dump(),public=True).json()
    # No session is issued to a project user without membership in this app.
    user=claims(result['access_token'])
    members=cloud.rows('halo_members',{'user_id':'eq.'+user['sub'],'active':'eq.true','select':'role'},1)
    if not members: raise HTTPException(403,'Ask the project administrator to add your team membership.')
    cookies(response,request,result)
    return {'signed_in':True,'role':members[0]['role']}


@router.post('/refresh')
def refresh(request:Request,response:Response):
    csrf(request)
    token=request.cookies.get(REFRESH)
    if not token: raise HTTPException(401,'Sign in again.')
    result=cloud.request('POST','/auth/v1/token',params={'grant_type':'refresh_token'},payload={'refresh_token':token},public=True).json()
    cookies(response,request,result)
    return {'renewed':True}


@router.get('/me')
def me(request:Request): return identity(request)


@router.get('/backend')
def backend(request:Request):
    identity(request)
    return {**cloud.health(),'evidence_bucket':'halo-evidence','access':'server mediated; client table access denied',
            'physical_switching':os.getenv('HALO_ALLOW_CONTROL')=='1'}


@router.post('/logout')
def logout(request:Request,response:Response):
    csrf(request)
    token=request.cookies.get(ACCESS)
    if token:
        try: cloud.request('POST','/auth/v1/logout',params={'scope':'local'},public=True,bearer=token)
        except HTTPException: pass
    response.delete_cookie(ACCESS,path='/api'); response.delete_cookie(REFRESH,path='/api/auth')
    response.delete_cookie(LOCAL,path='/api')
    return {'signed_out':True}


@router.get('/members')
def members(request:Request):
    identity(request,'admin')
    return {'members':cloud.rpc('halo_team_directory')}


class Membership(BaseModel):
    user_id:uuid.UUID|None=None
    email:str|None=Field(default=None,min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    role:str=Field(pattern='^(viewer|operator|admin)$')
    active:bool=True

    @model_validator(mode='after')
    def identifier(self):
        if (self.user_id is None)==(self.email is None):
            raise ValueError('Provide an email address or an account ID.')
        return self


@router.put('/members')
def membership(payload:Membership,request:Request):
    csrf(request); actor=identity(request,'admin')
    user_id=str(payload.user_id) if payload.user_id else None
    if payload.email:
        matches=cloud.rpc('halo_account_by_email',{'p_email':payload.email})
        if not matches: raise HTTPException(404,'No account matches this email. Ask your colleague to contact the account administrator.')
        user_id=str(matches[0]['user_id'])
    if user_id==actor['user_id'] and (payload.role!='admin' or not payload.active):
        raise HTTPException(409,'An administrator cannot remove their own access.')
    value={'user_id':user_id,'role':payload.role,'active':payload.active}
    existing=cloud.rows('halo_members',{'user_id':'eq.'+user_id},1)
    if existing: cloud.request('PATCH','/rest/v1/halo_members',params={'user_id':'eq.'+user_id},payload={'role':payload.role,'active':payload.active})
    else: cloud.request('POST','/rest/v1/halo_members',payload=value)
    return {'saved':True,**value}
