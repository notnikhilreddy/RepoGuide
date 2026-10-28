import type {ReactNode} from 'react';
import {useEffect,useState} from 'react';
import {authEnabled,authManager} from '../lib/auth';
let callbackOnce: Promise<void> | null = null;

export function AuthGate({children}:{children:ReactNode}){
  const [status,setStatus]=useState<'loading'|'ready'|'login'|'error'>(authEnabled?'loading':'ready');
  const [message,setMessage]=useState('');
  useEffect(()=>{
    if(!authManager)return;
    let live=true;
    (async()=>{
      try{
        if(new URLSearchParams(location.search).has('code')){
          if(!callbackOnce)callbackOnce=authManager.signinRedirectCallback().then(()=>{history.replaceState({},'', '/');});
          await callbackOnce;
        }
        const user=await authManager.getUser();
        if(live)setStatus(user && !user.expired?'ready':'login');
      }catch(e){if(live){setMessage(e instanceof Error?e.message:'Authentication failed');setStatus('error')}}
    })();
    return()=>{live=false};
  },[]);
  if(status==='ready')return <>{children}</>;
  return <div style={{minHeight:'100vh',display:'grid',placeItems:'center',background:'#0d1117',color:'#e6edf3',fontFamily:'system-ui'}}>
    <div style={{maxWidth:440,padding:40,border:'1px solid #30363d',borderRadius:14}}>
      <h2>RepoGuide</h2><p style={{color:'#8b949e'}}>Private engineering demo</p>
      {status==='loading'?<p>Checking session…</p>:<>
        {status==='error'&&<p role="alert">{message}</p>}
        <button onClick={()=>void authManager?.signinRedirect()} style={{padding:'10px 18px',background:'#238636',border:0,color:'white',borderRadius:6,cursor:'pointer'}}>Sign in with Cognito</button>
      </>}
    </div>
  </div>
}
