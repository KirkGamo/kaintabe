-- 013: one Telegram account may be BOTH an individual (flash-offer list) and a partner org's
-- representative. 009's unique index was per (chat, bot) across all recipient types, which blocked
-- an individual from registering an org. Make it one recipient per (chat, bot, type).

drop index recipients_telegram_chat_bot_idx;

create unique index recipients_telegram_chat_bot_type_idx
  on recipients (telegram_chat_id, via_bot, type) where telegram_chat_id is not null;
