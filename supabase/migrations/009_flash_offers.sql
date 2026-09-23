-- 009: flash offers - escalated listings are pushed via Telegram to opted-in individuals nearby.

alter table recipients
  add column active  boolean not null default true,  -- individuals opt out with /stop
  add column via_bot text;                           -- bot username they signed up through (dev vs prod)

create unique index recipients_telegram_chat_bot_idx
  on recipients (telegram_chat_id, via_bot) where telegram_chat_id is not null;

alter table donations add column flash_offer_count integer not null default 0;

-- One row per (listing, person) ever offered: the primary key is the "send once" guarantee.
create table flash_offers (
  donation_id  uuid not null references donations(id) on delete cascade,
  recipient_id uuid not null references recipients(id) on delete cascade,
  sent_at      timestamptz not null default now(),
  primary key (donation_id, recipient_id)
);
alter table flash_offers enable row level security;  -- no browser access

-- Reserve the offers this worker should send now: escalated listings x active individuals of
-- this bot within their own pickup range, not offered before. Inserting first means two workers
-- can never both send the same offer.
create function claim_flash_offers(p_bot text)
returns table (
  donation_id uuid, recipient_id uuid, chat_id bigint, food_type text, quantity text,
  donor_name text, photo_url text, lat double precision, lng double precision,
  expires_at timestamptz, distance_m double precision
)
language plpgsql
set search_path = public, extensions
as $$
begin
  return query
  with reserved as (
    insert into flash_offers (donation_id, recipient_id)
    select d.id, r.id
      from donations d
      join recipients r
        on r.type = 'individual' and r.active and r.via_bot = p_bot and r.telegram_chat_id is not null
       and st_dwithin(d.location, r.location, least(r.service_radius_m, d.search_radius_m))
     where d.status = 'escalated' and d.expires_at > now()
    on conflict do nothing
    returning flash_offers.donation_id, flash_offers.recipient_id
  ),
  counted as (
    update donations d
       set flash_offer_count = d.flash_offer_count + x.n
      from (select reserved.donation_id as id, count(*) as n from reserved group by reserved.donation_id) x
     where d.id = x.id
  )
  select d.id, r.id, r.telegram_chat_id, d.food_type, d.quantity, d.donor_name, d.photo_url,
         d.lat, d.lng, d.expires_at, st_distance(d.location, r.location)
    from reserved
    join donations d on d.id = reserved.donation_id
    join recipients r on r.id = reserved.recipient_id;
end;
$$;

revoke execute on function claim_flash_offers(text) from public, anon, authenticated;

-- Individuals can have long names from Telegram; the browser never sees their chat ids (see 001).
