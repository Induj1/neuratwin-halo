/* Same-origin session cookies. Supabase secret and user JWTs never enter JS. */
(()=>{'use strict';
const $=id=>document.getElementById(id);let cloud=false,ownerToken='',renewal=null;
const temporary=new Map();
function clearPrivateCache(clearCapabilities=false){if(clearCapabilities)for(const key of Object.keys(sessionStorage))if(/^(halo-arena-|arena-judge-)/.test(key))sessionStorage.removeItem(key);for(const key of Object.keys(localStorage))if(/^halo-(snapshot|incidents|draft)/.test(key))localStorage.removeItem(key);temporary.clear();}
const cache={getItem:key=>cloud?(temporary.get(key)||null):localStorage.getItem(key),setItem:(key,value)=>cloud?temporary.set(key,value):localStorage.setItem(key,value),removeItem:key=>cloud?temporary.delete(key):localStorage.removeItem(key)};
async function request(url,options={}){
 const headers=new Headers(options.headers||{});if(/^Bearer\s*$/i.test(headers.get('Authorization')||''))headers.delete('Authorization');if(ownerToken&&!headers.has('Authorization'))headers.set('Authorization','Bearer '+ownerToken);
 let response=await fetch(url,{...options,headers,cache:'no-store',credentials:'same-origin'});
 if(response.status===401&&cloud&&!ownerToken&&!url.startsWith('/api/auth/')){
  if(!renewal)renewal=fetch('/api/auth/refresh',{method:'POST',credentials:'same-origin'}).finally(()=>{renewal=null;});
  const renewed=await renewal;if(renewed.ok)response=await fetch(url,{...options,headers,cache:'no-store',credentials:'same-origin'});
 }
 return response;
}
async function status(){
 const response=await request('/api/auth/me');if(!response.ok)throw Error('Sign in with a NeuraTwin team account.');
 const user=await response.json();$('access').textContent=user.mode==='local operator'?'Local owner':user.role+' · Team';
 $('auth-identity').textContent=(user.email||'This computer')+' · '+user.role;
 const health=await request('/api/auth/backend');const data=await health.json();
 $('cloud-health').textContent=health.ok?'Supabase connected · schema '+data.schema_version:'Cloud unavailable';
 $('cloud-detail').textContent=health.ok?'Telemetry, investigations and model evidence persist in the cloud. Photos are stored in a private bucket.':data.detail;
 $('team-admin').hidden=user.role!=='admin';$('sign-out').hidden=user.mode!=='supabase';
 if(user.role==='admin')await members();return user;
}
async function members(){const r=await request('/api/auth/members');if(!r.ok)return;const d=await r.json();$('team-list').textContent=d.members.length?d.members.map(m=>`${m.user_id} · ${m.role} · ${m.active?'active':'disabled'}`).join('\n'):'No team accounts yet. Create an account with scripts/supabase_admin.py, then sign in here.';}
async function init(){
 const response=await fetch('/api/auth/config',{cache:'no-store'});if(!response.ok)throw Error('Access configuration unavailable');
 cloud=(await response.json()).enabled;$('cloud-account').hidden=!cloud;$('cloud-panel').hidden=!cloud;
 if(cloud)clearPrivateCache();return cloud;
}
function setToken(token){ownerToken=token||'';}
$('cloud-login').addEventListener('submit',async event=>{event.preventDefault();const b=$('sign-in');b.disabled=true;$('auth-error').textContent='Signing in…';try{
 const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:$('team-email').value.trim(),password:$('team-password').value})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Sign-in failed');
 sessionStorage.removeItem('halo-token');ownerToken='';clearPrivateCache(true);$('team-password').value='';location.reload();
 }catch(e){$('auth-error').textContent=e.message;}finally{b.disabled=false;}});
$('sign-out').onclick=async()=>{const r=await fetch('/api/auth/logout',{method:'POST'});if(!r.ok){$('auth-error').textContent='Sign-out failed. Try again.';return;}sessionStorage.removeItem('halo-token');clearPrivateCache(true);location.reload();};
$('member-form').onsubmit=async event=>{event.preventDefault();const b=$('save-member');b.disabled=true;try{const r=await request('/api/auth/members',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:$('member-id').value.trim(),role:$('member-role').value,active:$('member-active').checked})});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Enter a valid Supabase user UUID.');await members();$('member-message').textContent='Membership saved. Permissions apply on the next request.';}catch(e){$('member-message').textContent=e.message;}finally{b.disabled=false;}};
window.HaloAuth={fetch:request,init,status,setToken,cache,isCloud:()=>cloud,blocked:()=>{clearPrivateCache(true);$('connection').textContent='Sign-in required';$('auth-error').textContent='Your session or team access is unavailable.';if(!$('access-dialog').open)$('access-dialog').showModal();}};
})();
