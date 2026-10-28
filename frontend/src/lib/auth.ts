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
  automaticSilentRenew:false,
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
