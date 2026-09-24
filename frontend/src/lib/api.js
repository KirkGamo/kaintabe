import { compressImage } from './image'
import { API_URL } from './supabase'

// Telegram signs this when the map is opened as a Mini App; the backend verifies it to know
// which org is acting. Outside Telegram it's empty and the map is read-only.
export const telegramInitData = () => window.Telegram?.WebApp?.initData || ''

async function request(path, init = {}) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      ...init,
      headers: { ...(init.headers ?? {}), 'X-Telegram-Init-Data': telegramInitData() },
    })
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.")
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail ?? `Something went wrong (HTTP ${res.status}).`)
  return data
}

export const getMe = () => request('/api/me', { method: 'GET' })
export const getConfig = () => request('/api/config', { method: 'GET' })

export const claimDonation = (donationId, recipientId) =>
  request('/api/claims', {
    headers: { 'Content-Type': 'application/json' },
    // recipient_id is ignored by the current API (the org comes from Telegram); kept only so a
    // briefly-older backend during a deploy still accepts the request
    body: JSON.stringify({ donation_id: donationId, recipient_id: recipientId }),
  })

export async function confirmPickup(claimId, recipientId, photoFile) {
  const photo = await compressImage(photoFile)
  const form = new FormData()
  form.append('recipient_id', recipientId)
  form.append('photo', photo, 'pickup.jpg')
  return request(`/api/claims/${claimId}/confirm`, { body: form })
}
