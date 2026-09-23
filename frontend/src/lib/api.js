import { compressImage } from './image'
import { API_URL } from './supabase'

async function request(path, init) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, { method: 'POST', ...init })
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.")
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail ?? `Something went wrong (HTTP ${res.status}).`)
  return data
}

export const claimDonation = (donationId, recipientId) =>
  request('/api/claims', {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ donation_id: donationId, recipient_id: recipientId }),
  })

export async function confirmPickup(claimId, recipientId, photoFile) {
  const photo = await compressImage(photoFile)
  const form = new FormData()
  form.append('recipient_id', recipientId)
  form.append('photo', photo, 'pickup.jpg')
  return request(`/api/claims/${claimId}/confirm`, { body: form })
}
