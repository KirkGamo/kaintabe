import { useCallback, useEffect, useRef, useState } from 'react'
import { getConfig, getRoleMap, telegramInitData } from '../lib/api'

const EMPTY = {
  org: null, donor: null, individual: null, inRange: [], myPickups: [], myListings: [], flashOffers: [], firstName: null,
}

/**
 * Who opened the map, and the exact data their roles may see (from /api/map).
 *  inTelegram — opened as a Telegram Mini App (signed identity available)
 *  org / donor / individual — the roles this Telegram user holds (any combination)
 *  inRange    — org: exact listings within its reach
 *  myPickups  — org/individual: their claims awaiting pickup (with claim_id, reserved_price)
 *  myListings — donor: their own live/claimed listings
 *  flashOffers — individual: flash offers they got that are still free to take (no exact spot yet)
 *  botUrl     — t.me link to the bot, for "Claim in Telegram" outside it
 * Re-fetches when `changedAt` changes (any public listing changed), so exact data stays live.
 */
export function useTelegramIdentity(changedAt) {
  const inTelegram = Boolean(telegramInitData())
  const [state, setState] = useState({ ...EMPTY, loading: inTelegram, error: null })
  const [botUrl, setBotUrl] = useState(null)
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    if (!inTelegram) return
    try {
      const v = await getRoleMap()
      setState({
        loading: false, error: null, firstName: v.first_name, org: v.org, donor: v.donor, individual: v.individual,
        inRange: v.in_range, myPickups: v.my_pickups, myListings: v.my_listings, flashOffers: v.flash_offers ?? [],
      })
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e.message }))
    }
  }, [inTelegram])

  useEffect(() => {
    getConfig()
      .then((c) => setBotUrl(`https://t.me/${c.bot_username}`))
      .catch(() => {})
    if (!inTelegram) return
    const tg = window.Telegram.WebApp
    tg.ready()
    tg.expand()
    // Otherwise a downward swipe in the listings sheet minimizes the Mini App instead of scrolling
    // (Telegram 7.7+; older clients don't have it)
    tg.disableVerticalSwipes?.()
    refresh()
  }, [inTelegram, refresh])

  // A listing changed somewhere: refetch this person's exact view (debounced; changes come in bursts)
  useEffect(() => {
    if (!inTelegram || !changedAt) return
    clearTimeout(timer.current)
    timer.current = setTimeout(refresh, 600)
    return () => clearTimeout(timer.current)
  }, [changedAt, inTelegram, refresh])

  return { inTelegram, botUrl, refresh, ...state }
}
