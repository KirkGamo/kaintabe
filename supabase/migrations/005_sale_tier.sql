-- 005: discount-sale tier.
--   A 'sale' listing's price decays linearly over the same window that triggers auto-widen
--   (widen_after_minutes, measured from radius_widened_at). When the window ends unsold, it
--   converts to a free donation and follows the normal widen/escalate path from there.
--   Reserving locks the price at that moment; the buyer pays in person at pickup.

alter table claims add column reserved_price numeric;

-- Sale listings: decay the price, or convert to a free donation once the window is over.
create function decay_sale_prices()
returns integer
language plpgsql
set search_path = public, extensions
as $$
declare
  v_secs numeric := (select value from app_config where key = 'widen_after_minutes') * 60;
  v_converted integer;
begin
  update donations
     set listing_type = 'donation',
         current_price = null,
         radius_widened_at = now()          -- the donation pool's widen clock starts now
   where status = 'posted'
     and listing_type = 'sale'
     and radius_widened_at <= now() - make_interval(secs => v_secs);
  get diagnostics v_converted = row_count;

  update donations
     set current_price = greatest(
           1,
           round(original_price * (1 - extract(epoch from (now() - radius_widened_at)) / v_secs))
         )
   where status = 'posted'
     and listing_type = 'sale'
     and current_price is distinct from greatest(
           1,
           round(original_price * (1 - extract(epoch from (now() - radius_widened_at)) / v_secs))
         );

  return v_converted;
end;
$$;

-- Only donations widen/escalate; sale listings convert first (above).
create or replace function widen_unclaimed()
returns integer
language plpgsql
set search_path = public, extensions
as $$
declare
  v_interval interval := make_interval(secs => (select value from app_config where key = 'widen_after_minutes') * 60);
  v_max      integer  := (select value::int from app_config where key = 'radius_max_m');
  v_widened  integer;
  v_escalated integer;
begin
  update donations
     set search_radius_m = least(search_radius_m * 2, v_max),
         radius_widened_at = now()
   where status = 'posted'
     and listing_type = 'donation'
     and expires_at > now()
     and search_radius_m < v_max
     and radius_widened_at <= now() - v_interval;
  get diagnostics v_widened = row_count;

  update donations
     set status = 'escalated'
   where status = 'posted'
     and listing_type = 'donation'
     and expires_at > now()
     and search_radius_m >= v_max
     and radius_widened_at <= now() - v_interval;
  get diagnostics v_escalated = row_count;

  return v_widened + v_escalated;
end;
$$;

create or replace function kaintabe_tick()
returns void
language plpgsql
set search_path = public, extensions
as $$
begin
  perform expire_donations();
  perform decay_sale_prices();
  perform widen_unclaimed();
end;
$$;

-- Claim = reserve for sale listings: lock the price shown at that moment.
create or replace function claim_donation(p_donation_id uuid, p_recipient_id uuid)
returns claims
language plpgsql
set search_path = public, extensions
as $$
declare
  v_claim claims;
  v_price numeric;
begin
  update donations d
     set status = 'claimed'
    from recipients r
   where d.id = p_donation_id
     and r.id = p_recipient_id
     and d.status in ('posted', 'escalated')
     and d.expires_at > now()
     and st_dwithin(d.location, r.location, d.search_radius_m)
  returning case when d.listing_type = 'sale' then d.current_price end into v_price;

  if not found then
    raise exception 'not_available' using errcode = 'P0001';
  end if;

  insert into claims (donation_id, recipient_id, reserved_price)
  values (p_donation_id, p_recipient_id, v_price)
  returning * into v_claim;

  return v_claim;
end;
$$;

revoke execute on function decay_sale_prices() from public, anon, authenticated;
revoke execute on function claim_donation(uuid, uuid) from public, anon, authenticated;
