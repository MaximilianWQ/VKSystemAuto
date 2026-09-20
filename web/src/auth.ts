/** Passkey: перевод между JSON сервера и WebAuthn API браузера.

Браузер требует ArrayBuffer там, где сервер присылает base64url, и наоборот —
возвращает ArrayBuffer там, где серверу нужен base64url. Всё преобразование
собрано здесь, чтобы не растекалось по экранам. */

import { api } from './api'

export const passkeySupported = () =>
  typeof window !== 'undefined' &&
  typeof window.PublicKeyCredential === 'function' &&
  !!navigator.credentials

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4))
  // Буфер выделяем явно: WebAuthn требует ArrayBuffer, а Uint8Array.from
  // в новых версиях TypeScript даёт ArrayBufferLike, который не подходит.
  const bytes = new Uint8Array(new ArrayBuffer(binary.length))
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function toBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

type ServerOptions = Record<string, unknown>

function prepareCreation(options: ServerOptions): PublicKeyCredentialCreationOptions {
  const source = options as never as {
    challenge: string
    user: { id: string; name: string; displayName: string }
    excludeCredentials?: { id: string; type: 'public-key' }[]
  }
  return {
    ...(options as object),
    challenge: fromBase64Url(source.challenge),
    user: { ...source.user, id: fromBase64Url(source.user.id) },
    excludeCredentials: (source.excludeCredentials ?? []).map((item) => ({
      ...item,
      id: fromBase64Url(item.id),
    })),
  } as unknown as PublicKeyCredentialCreationOptions
}

function prepareRequest(options: ServerOptions): PublicKeyCredentialRequestOptions {
  const source = options as never as {
    challenge: string
    allowCredentials?: { id: string; type: 'public-key' }[]
  }
  return {
    ...(options as object),
    challenge: fromBase64Url(source.challenge),
    allowCredentials: (source.allowCredentials ?? []).map((item) => ({
      ...item,
      id: fromBase64Url(item.id),
    })),
  } as unknown as PublicKeyCredentialRequestOptions
}

function serializeAttestation(credential: PublicKeyCredential) {
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: toBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64Url(response.clientDataJSON),
      attestationObject: toBase64Url(response.attestationObject),
    },
  }
}

function serializeAssertion(credential: PublicKeyCredential) {
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: toBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64Url(response.clientDataJSON),
      authenticatorData: toBase64Url(response.authenticatorData),
      signature: toBase64Url(response.signature),
      userHandle: response.userHandle ? toBase64Url(response.userHandle) : null,
    },
  }
}

/** Регистрирует passkey по одноразовой ссылке и открывает сессию. */
export async function registerPasskey(token: string, name: string) {
  const options = await api.post<ServerOptions>('/api/auth/register/options', { token })
  const credential = (await navigator.credentials.create({
    publicKey: prepareCreation(options),
  })) as PublicKeyCredential | null
  if (!credential) throw new Error('Браузер не создал ключ')

  await api.post('/api/auth/register/verify', {
    token,
    name,
    credential: serializeAttestation(credential),
  })
}

/** Вход существующим ключом. */
export async function loginWithPasskey() {
  const options = await api.post<ServerOptions>('/api/auth/login/options')
  const credential = (await navigator.credentials.get({
    publicKey: prepareRequest(options),
  })) as PublicKeyCredential | null
  if (!credential) throw new Error('Браузер не вернул ключ')

  await api.post('/api/auth/login/verify', {
    credential: serializeAssertion(credential),
  })
}

export const logout = () => api.post('/api/auth/logout')
