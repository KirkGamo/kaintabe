import { API_URL } from './supabase'

async function post(path, body) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.")
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail ?? `Something went wrong (HTTP ${res.status}).`)
  return data
}

export const claimDonation = (donationId, recipientId) =>
  post('/api/claims', { donation_id: donationId, recipient_id: recipientId })
