-- 019: never alert or flash-offer someone about their own food.
-- One Telegram account can be a donor and an org and/or individual at once; before this, posting
-- food near your own org pinged you with "new food near you - claim it?" for your own listing.
-- Same functions as 014 / 009, plus one condition: the recipient's chat isn't the donor's chat.

create or replace function claim_org_alerts(p_bot text)
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
      join donors o on o.id = d.donor_id
      join recipients r
        on r.type = 'partner_org' and r.via_bot = p_bot and r.telegram_chat_id is not null
       and st_dwithin(d.location, r.location, least(d.search_radius_m, r.service_radius_m))
       and r.telegram_chat_id is distinct from o.telegram_chat_id
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

create or replace function claim_flash_offers(p_bot text)
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
      join donors o on o.id = d.donor_id
      join recipients r
        on r.type = 'individual' and r.active and r.via_bot = p_bot and r.telegram_chat_id is not null
       and st_dwithin(d.location, r.location, least(r.service_radius_m, d.search_radius_m))
       and r.telegram_chat_id is distinct from o.telegram_chat_id
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

revoke execute on function claim_org_alerts(text) from public, anon, authenticated;
revoke execute on function claim_flash_offers(text) from public, anon, authenticated;
