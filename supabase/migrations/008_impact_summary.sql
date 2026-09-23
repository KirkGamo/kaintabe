-- 008: impact dashboard numbers in one call (read-only; safe for the browser key).
-- "Rescued" = a confirmed pickup (status completed = donated, sold = discount sale).
-- Factors: 1 meal ~ 0.4 kg (WRAP uses 420 g); 1 kg food waste ~ 2.5 kg CO2e
-- (FAO 2013 Food Wastage Footprint: 3.3 Gt CO2e / 1.3 Gt food wasted).

create function impact_summary(p_days integer default 7)
returns jsonb
language sql stable
security definer
set search_path = public, extensions
as $$
  with rescued as (
    select d.id, d.food_type, d.listing_type, coalesce(d.est_kg, 0) as kg, d.created_at,
           c.claimed_at, c.confirmed_at, c.reserved_price, r.name as recipient_name
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
    select days.day,
           coalesce(sum(r.kg), 0) as kg,
           count(r.id)            as pickups
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

grant execute on function impact_summary(integer) to anon, authenticated;
