-- 015: privacy, part 1 (additive; safe while the previous web app is still live).
--   * a public_listings table mirrors each donation with an APPROXIMATE location (~500 m grid cell),
--     no donor name, no photo -> the public live map (projector, judges) and its Realtime feed
--   * nearby_donations (exact rows for any recipient id) becomes backend-only
--   * the impact dashboard shows individuals as "a neighbor"
-- Part 2 (017) removes anon read access to donations/claims/individuals once the new web app is live.

-- ~500 m grid (0.0045 deg of latitude; longitude cells are ~1.5% narrower at Iloilo's latitude).
-- Points are moved to the CENTER of their cell, so nearby homes share one public spot.
create function snap_to_grid(v double precision)
returns double precision
language sql immutable
as $$ select (floor(v / 0.0045) + 0.5) * 0.0045 $$;

create table public_listings (
  id                uuid primary key references donations(id) on delete cascade,
  status            text not null,
  listing_type      text not null,
  food_type         text not null,
  est_kg            numeric,
  original_price    numeric,
  current_price     numeric,
  allergens         text[],
  ai_assisted       boolean not null default false,
  safety_checked    boolean not null default false,
  expires_at        timestamptz not null,
  created_at        timestamptz not null,
  search_radius_m   integer not null,
  radius_widened_at timestamptz not null,
  flash_offer_count integer not null default 0,
  lat               double precision not null,  -- approximate (grid cell center)
  lng               double precision not null
);

create function sync_public_listing()
returns trigger
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  insert into public_listings (id, status, listing_type, food_type, est_kg, original_price, current_price,
                               allergens, ai_assisted, safety_checked, expires_at, created_at,
                               search_radius_m, radius_widened_at, flash_offer_count, lat, lng)
  values (new.id, new.status, new.listing_type, new.food_type, new.est_kg, new.original_price, new.current_price,
          new.allergens, new.ai_assisted,
          coalesce((new.safety_checklist->>'hygienic')::boolean and (new.safety_checklist->>'safe_temperature')::boolean
                   and (new.safety_checklist->>'contents_known')::boolean, false),
          new.expires_at, new.created_at, new.search_radius_m, new.radius_widened_at, new.flash_offer_count,
          snap_to_grid(new.lat), snap_to_grid(new.lng))
  on conflict (id) do update set
    status = excluded.status, listing_type = excluded.listing_type, food_type = excluded.food_type,
    est_kg = excluded.est_kg, original_price = excluded.original_price, current_price = excluded.current_price,
    allergens = excluded.allergens, ai_assisted = excluded.ai_assisted, safety_checked = excluded.safety_checked,
    expires_at = excluded.expires_at, search_radius_m = excluded.search_radius_m,
    radius_widened_at = excluded.radius_widened_at, flash_offer_count = excluded.flash_offer_count,
    lat = excluded.lat, lng = excluded.lng;
  return null;
end;
$$;

create trigger donations_to_public
  after insert or update on donations
  for each row execute function sync_public_listing();
-- (deletes cascade through the foreign key)

-- Backfill every existing donation
update donations set status = status;

alter table public_listings enable row level security;
create policy "public read" on public_listings for select to anon, authenticated using (true);
alter publication supabase_realtime add table public_listings;

-- nearby_donations returns exact rows for any recipient id: backend only now
revoke execute on function nearby_donations(uuid) from anon, authenticated;

-- Impact dashboard: individuals are shown as "a neighbor", never by name
create or replace function impact_summary(p_days integer default 7)
returns jsonb
language sql stable
security definer
set search_path = public, extensions
as $$
  with rescued as (
    select d.id, d.food_type, d.listing_type, coalesce(d.est_kg, 0) as kg, d.created_at,
           c.claimed_at, c.confirmed_at, c.reserved_price,
           case when r.type = 'individual' then 'a neighbor' else r.name end as recipient_name
      from donations d
      join claims c on c.donation_id = d.id
      join recipients r on r.id = c.recipient_id
     where d.status in ('completed', 'sold') and c.confirmed_at is not null
  ),
  totals as (
    select coalesce(sum(kg), 0)                                          as kg_rescued,
           coalesce(sum(kg) filter (where listing_type = 'donation'), 0) as kg_donated,
           coalesce(sum(kg) filter (where listing_type = 'sale'), 0)     as kg_sold,
           count(*)                                                      as pickups,
           coalesce(sum(reserved_price), 0)                              as pesos_to_donors
      from rescued
  ),
  claim_speed as (
    select percentile_cont(0.5) within group (
             order by extract(epoch from (c.claimed_at - d.created_at)) / 60
           ) as median_minutes_to_claim
      from claims c join donations d on d.id = c.donation_id
  ),
  days as (
    select generate_series(
             (now() at time zone 'Asia/Manila')::date - (p_days - 1),
             (now() at time zone 'Asia/Manila')::date,
             interval '1 day'
           )::date as day
  ),
  daily as (
    select days.day, coalesce(sum(r.kg), 0) as kg, count(r.id) as pickups
      from days
      left join rescued r on (r.confirmed_at at time zone 'Asia/Manila')::date = days.day
     group by days.day
     order by days.day
  ),
  recent as (
    select food_type, listing_type, kg, recipient_name, confirmed_at
      from rescued order by confirmed_at desc limit 5
  )
  select jsonb_build_object(
    'kg_rescued',      round(t.kg_rescued, 1),
    'kg_donated',      round(t.kg_donated, 1),
    'kg_sold',         round(t.kg_sold, 1),
    'meals',           round(t.kg_rescued / 0.4),
    'co2e_kg',         round(t.kg_rescued * 2.5, 1),
    'pickups',         t.pickups,
    'pesos_to_donors', t.pesos_to_donors,
    'median_minutes_to_claim', round(cs.median_minutes_to_claim::numeric, 1),
    'listings_posted', (select count(*) from donations),
    'open_now',        (select count(*) from donations where status in ('posted', 'escalated') and expires_at > now()),
    'daily',  (select jsonb_agg(jsonb_build_object('day', day, 'kg', round(kg, 1), 'pickups', pickups)) from daily),
    'recent', coalesce((select jsonb_agg(to_jsonb(recent)) from recent), '[]'::jsonb)
  )
  from totals t, claim_speed cs;
$$;
