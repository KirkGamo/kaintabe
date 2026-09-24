import { useEffect, useState } from 'react'
import { getConfig, getMe, telegramInitData } from '../lib/api'

/**
 * Who opened the map.
 *  inTelegram — opened as a Telegram Mini App (signed identity available)
 *  org        — the partner org this Telegram user represents, or null
 *  botUrl     — t.me link to the bot, for "Claim in Telegram" outside it
 */
export function useTelegramIdentity() {
  const inTelegram = Boolean(telegramInitData())
  const [state, setState] = useState({ loading: inTelegram, org: null, firstName: null, error: null })
  const [botUrl, setBotUrl] = useState(null)

  useEffect(() => {
    getConfig()
      .then((c) => setBotUrl(`https://t.me/${c.bot_username}`))
      .catch(() => {})
    if (!inTelegram) return
    const tg = window.Telegram.WebApp
    tg.ready()
    tg.expand()
    getMe()
      .then((me) => setState({ loading: false, org: me.org, firstName: me.telegram_user?.first_name, error: null }))
      .catch((e) => setState({ loading: false, org: null, firstName: null, error: e.message }))
  }, [inTelegram])

  return { inTelegram, botUrl, ...state }
}
