import { UserManager, WebStorageStateStore } from 'oidc-client-ts';

const issuer=import.meta.env.VITE_COGNITO_ISSUER as string | undefined;
const clientId=import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
export const authEnabled=Boolean(issuer&&clientId);
export const authManager = authEnabled ? new UserManager({
  authority:issuer!,client_id:clientId!,
  redirect_uri:window.location.origin+'/',
  post_logout_redirect_uri:window.location.origin+'/',
  response_type:'code',scope:'openid email profile',
  userStore:new WebStorageStateStore({store:window.sessionStorage}),
  automaticSilentRenew:true,
  accessTokenExpiringNotificationTimeInSeconds:90,
}) : null;

export async function accessToken():Promise<string | null>{
  if(!authManager)return null;
  const user=await authManager.getUser();
  if(!user || user.expired)return null;
  return user.access_token;
}

export async function requireAuthHeaders():Promise<HeadersInit>{
  if(!authEnabled)return {};
  const token=await accessToken();
  if(!token)throw new Error('Session expired. Sign in again.');
  return {Authorization:`Bearer ${token}`};
}

export async function cognito(action:string,values:Record<string,unknown>){
  if(!issuer||!clientId)throw new Error('Authentication is not configured');
  const response=await fetch(new URL(issuer).origin,{method:'POST',headers:{'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':`AWSCognitoIdentityProviderService.${action}`},body:JSON.stringify({ClientId:clientId,...values})});
  const data=await response.json();
  if(!response.ok){const code=String(data.__type||'').split('#').pop();const messages:Record<string,string>={UsernameExistsException:'An account with this email already exists. Sign in or reset your password.',InvalidPasswordException:'Use at least 12 characters with uppercase, lowercase, a number, and a symbol.',CodeMismatchException:'That verification code is not correct.',ExpiredCodeException:'This code expired. Request a new one.',LimitExceededException:'Too many attempts. Please wait before trying again.',TooManyRequestsException:'Too many attempts. Please try again shortly.',NotAuthorizedException:'This request is not authorized. Try signing in again.',UserNotFoundException:'Check your email address and try again.'};throw new Error(messages[code||'']||'Authentication request failed. Please try again.')}
  return data as Record<string,unknown>;
}

export async function signOut(){
  if(!authManager)return;
  const metadata=await authManager.metadataService.getMetadata();
  const endpoint=new URL('/logout',metadata.authorization_endpoint);
  endpoint.searchParams.set('client_id',clientId!);endpoint.searchParams.set('logout_uri',window.location.origin+'/');
  await authManager.removeUser();
  window.location.assign(endpoint.href);
}
