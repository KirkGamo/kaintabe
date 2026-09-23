-- 010: persisted bot conversation state, so a deploy/crash mid-post doesn't lose the donor's progress.
-- Keyed by bot id (token prefix) because the dev and prod bots share this database.
--   kind = 'user'         key = telegram user id          data = that user's user_data (drafts, profile)
--   kind = 'conv:<name>'  key = JSON of the conversation key (chat id, user id)   data = current state

create table bot_state (
  bot_id     text not null,
  kind       text not null,
  key        text not null,
  data       jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (bot_id, kind, key)
);

alter table bot_state enable row level security;  -- backend only; no browser access
