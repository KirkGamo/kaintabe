-- 014: alert partner orgs (via Telegram) when a claimable listing is within reach.
-- An org is alerted once per listing, when the listing's current search radius AND the org's own
-- service radius both cover it. Because this runs every notifier tick, a listing that widens into
-- range alerts the newly covered orgs then.

create table org_alerts (
  donation_id  uuid not null references donations(id) on delete cascade,
  recipient_id uuid not null references recipients(id) on delete cascade,
  sent_at      timestamptz not null default now(),
  primary key (donation_id, recipient_id)
);
alter table org_alerts enable row level security;  -- backend only

-- Reserve the alerts this bot should send now; the insert-first pattern means two workers
-- (e.g. local dev + Railway on different bots, or a double tick) never send the same alert twice.
create function claim_org_alerts(p_bot text)
returns table (
  donation_id uuid, recipient_id uuid, chat_id bigint, food_type text, quantity text, donor_name text,
  listing_type text, current_price numeric, lat double precision, lng double precision,
  expires_at timestamptz, distance_m double precision
)
language plpgsql
set search_path = public, extensions
as $$
begin
  return query
  with reserved as (
    insert into org_alerts (donation_id, recipient_id)
    select d.id, r.id
      from donations d
      join recipients r
        on r.type = 'partner_org' and r.via_bot = p_bot and r.telegram_chat_id is not null
       and st_dwithin(d.location, r.location, least(d.search_radius_m, r.service_radius_m))
     where d.status in ('posted', 'escalated') and d.expires_at > now()
    on conflict do nothing
    returning org_alerts.donation_id, org_alerts.recipient_id
  )
  select d.id, r.id, r.telegram_chat_id, d.food_type, d.quantity, d.donor_name,
         d.listing_type, d.current_price, d.lat, d.lng, d.expires_at, st_distance(d.location, r.location)
    from reserved
    join donations d on d.id = reserved.donation_id
    join recipients r on r.id = reserved.recipient_id;
end;
$$;

revoke execute on function claim_org_alerts(text) from public, anon, authenticated;
