-- 020: demo role switch. One presenter's Telegram account plays donor, org and individual on stage;
-- /demo (owner-only) "parks" the roles it isn't playing: the profile row stays, but its chat link is
-- removed and remembered here, so switching back restores it instantly.
-- A parked org must not look like an unclaimed seeded org (see repo.unlinked_orgs).

create table demo_parked (
  kind       text not null check (kind in ('donor', 'org', 'individual')),
  row_id     uuid not null,          -- donors.id or recipients.id
  chat_id    bigint not null,
  via_bot    text not null default '',  -- '' for donors (a donor profile is shared by both bots)
  parked_at  timestamptz not null default now(),
  primary key (kind, row_id)
);
alter table demo_parked enable row level security;  -- backend only
