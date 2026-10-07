/* Account sessions and team access. Infrastructure stays behind the API. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const roles={viewer:'Viewer',operator:'Operator',admin:'Administrator'};
let cloud=false,ownerToken='',renewal=null,currentUser=null;
const temporary=new Map();
function clearPrivateCache(clearCapabilities=false){
 if(clearCapabilities)for(const key of Object.keys(sessionStorage))if(/^(halo-arena-|arena-judge-)/.test(key))sessionStorage.removeItem(key);
 for(const key of Object.keys(localStorage))if(/^halo-(snapshot|incidents|draft)/.test(key))localStorage.removeItem(key);
 temporary.clear();
}
const cache={getItem:key=>cloud?(temporary.get(key)||null):localStorage.getItem(key),setItem:(key,value)=>cloud?temporary.set(key,value):localStorage.setItem(key,value),removeItem:key=>cloud?temporary.delete(key):localStorage.removeItem(key)};
async function request(url,options={}){
 const headers=new Headers(options.headers||{});
 if(/^Bearer\s*$/i.test(headers.get('Authorization')||''))headers.delete('Authorization');
 if(ownerToken&&!headers.has('Authorization'))headers.set('Authorization','Bearer '+ownerToken);
 let response=await fetch(url,{...options,headers,cache:'no-store',credentials:'same-origin'});
 if(response.status===401&&cloud&&!ownerToken&&!url.startsWith('/api/auth/')){
  if(!renewal)renewal=fetch('/api/auth/refresh',{method:'POST',credentials:'same-origin'}).finally(()=>{renewal=null;});
  const renewed=await renewal;
  if(renewed.ok)response=await fetch(url,{...options,headers,cache:'no-store',credentials:'same-origin'});
 }
 return response;
}
async function result(response,fallback){
 const data=await response.json();
 if(!response.ok)throw Error(response.status>=500?'This service is temporarily unavailable. Please try again.':typeof data.detail==='string'?data.detail:fallback);
 return data;
}
async function checkService(){
 try{
  const response=await request('/api/auth/backend');
  $('workspace-notice').hidden=response.ok;
 }catch(e){$('workspace-notice').hidden=false;}
}
async function status(){
 const response=await request('/api/auth/me');
 currentUser=await result(response,'Sign in to continue to your workspace.');
 $('access').textContent='Account';$('access').setAttribute('aria-label','Account and team settings');
 $('account-title').textContent='Your workspace';
 $('account-profile').hidden=false;
 $('account-name').textContent=currentUser.email||'Workspace administrator';
 $('account-role').textContent=roles[currentUser.role];
 $('account-context').textContent=currentUser.mode==='local operator'?'This device is authorized for local access.':'Your access applies across this workspace.';
 $('account-avatar').textContent=currentUser.email?currentUser.email.slice(0,2).toUpperCase():'NR';
 $('cloud-login').hidden=true;$('switch-account').hidden=false;
 $('team-admin').hidden=currentUser.role!=='admin';
 $('sign-out').hidden=currentUser.mode!=='supabase';
 $('auth-error').textContent='';
 await checkService();return currentUser;
}
async function saveMember(payload){
 const response=await request('/api/auth/members',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 return result(response,'Check the email address and selected role.');
}
function memberRow(member){
 const row=document.createElement('form');row.className='team-member';
 const identity=document.createElement('div');identity.className='team-member-identity';
 const name=document.createElement('strong');name.textContent=member.email||'Team member';
 const state=document.createElement('span');state.textContent=member.active?'Active member':'Access paused';
 identity.append(name,state);
 const select=document.createElement('select');select.setAttribute('aria-label','Role for '+(member.email||'team member'));
 for(const [value,label] of Object.entries(roles)){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}select.value=member.role;
 const label=document.createElement('label');label.className='member-access-toggle';
 const active=document.createElement('input');active.type='checkbox';active.checked=member.active;label.append(active,document.createTextNode('Access enabled'));
 const save=document.createElement('button');save.type='submit';save.textContent='Save';
 const isSelf=member.user_id===currentUser?.user_id;select.disabled=isSelf;active.disabled=isSelf;save.disabled=isSelf;
 const controls=document.createElement('div');controls.className='team-member-controls';controls.append(select,label,save);
 row.append(identity,controls);
 row.onsubmit=async event=>{event.preventDefault();save.disabled=true;$('member-message').textContent='';try{
  await saveMember({user_id:member.user_id,role:select.value,active:active.checked});
  member.role=select.value;member.active=active.checked;state.textContent=member.active?'Active member':'Access paused';
  $('member-message').textContent='Access updated.';
 }catch(e){$('member-message').textContent=e.message;}finally{save.disabled=isSelf;}};
 return row;
}
async function members(){
 $('team-list').textContent='Loading your team…';
 try{
  const data=await result(await request('/api/auth/members'),'Team access is unavailable.');
  $('team-list').replaceChildren();
  if(data.members.length)data.members.forEach(member=>$('team-list').append(memberRow(member)));
  else{const empty=document.createElement('p');empty.className='team-empty';empty.textContent='No team members have been added yet.';$('team-list').append(empty);}
 }catch(e){$('team-list').textContent=e.message;}
}
async function init(){
 const response=await fetch('/api/auth/config',{cache:'no-store'});
 const config=await result(response,'Unable to open your workspace. Please try again.');
 cloud=config.enabled;$('cloud-account').hidden=!cloud;$('legacy-access').hidden=cloud;
 if(cloud)clearPrivateCache();return cloud;
}
function setToken(token){ownerToken=token||'';}
$('cloud-login').addEventListener('submit',async event=>{
 event.preventDefault();const button=$('sign-in');button.disabled=true;button.textContent='Signing in…';$('auth-error').textContent='';
 try{
  await result(await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:$('team-email').value.trim(),password:$('team-password').value})}),'Check your email and password.');
  sessionStorage.removeItem('halo-token');ownerToken='';clearPrivateCache(true);$('team-password').value='';location.reload();
 }catch(e){$('auth-error').textContent=e.message;}finally{button.disabled=false;button.textContent='Sign in';}
});
$('switch-account').onclick=()=>{$('cloud-login').hidden=false;$('switch-account').hidden=true;$('team-email').focus();};
$('sign-out').onclick=async()=>{
 const button=$('sign-out');button.disabled=true;
 try{await result(await fetch('/api/auth/logout',{method:'POST'}),'Unable to sign out. Please try again.');sessionStorage.removeItem('halo-token');clearPrivateCache(true);location.reload();}
 catch(e){$('auth-error').textContent=e.message;button.disabled=false;}
};
$('team-admin').addEventListener('toggle',()=>{if($('team-admin').open)members();});
$('member-form').onsubmit=async event=>{
 event.preventDefault();const button=$('save-member');button.disabled=true;$('member-message').textContent='';
 try{await saveMember({email:$('member-email').value.trim(),role:$('member-role').value,active:true});$('member-email').value='';await members();$('member-message').textContent='Team access added.';}
 catch(e){$('member-message').textContent=e.message;}finally{button.disabled=false;}
};
$('workspace-retry').onclick=async()=>{const button=$('workspace-retry');button.disabled=true;await checkService();button.disabled=false;};
function blocked(){
 clearPrivateCache(true);currentUser=null;
 $('connection').textContent='Sign-in required';$('access').textContent='Sign in';$('account-title').textContent='Welcome to NeuraTwin';
 $('account-profile').hidden=true;$('team-admin').hidden=true;$('team-admin').open=false;
 $('cloud-login').hidden=!cloud;$('sign-out').hidden=true;$('switch-account').hidden=true;
 $('auth-error').textContent='Sign in to continue. If your access changed, contact your administrator.';
 if(!$('access-dialog').open)$('access-dialog').showModal();
}
window.HaloAuth={fetch:request,init,status,setToken,cache,isCloud:()=>cloud,blocked};
})();
