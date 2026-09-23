-- 006: compute the sale price at the exact moment of reserving.
-- The stored current_price is only refreshed every cron tick (15 s), so locking it in could be up
-- to one tick stale (e.g. P97 locked when the live price was P75 in demo mode). One formula now
-- serves the cron refresh and the reservation, matching what the web app displays.

create function sale_price_now(p_original numeric, p_since timestamptz)
returns numeric
language sql stable
set search_path = public, extensions
as $$
  select greatest(
    1,
    round(p_original * (1 - extract(epoch from (now() - p_since))
                            / ((select value from app_config where key = 'widen_after_minutes') * 60)))
  );
$$;

create or replace function decay_sale_prices()
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
         radius_widened_at = now()
   where status = 'posted'
     and listing_type = 'sale'
     and radius_widened_at <= now() - make_interval(secs => v_secs);
  get diagnostics v_converted = row_count;

  update donations
     set current_price = sale_price_now(original_price, radius_widened_at)
   where status = 'posted'
     and listing_type = 'sale'
     and current_price is distinct from sale_price_now(original_price, radius_widened_at);

  return v_converted;
end;
$$;

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
     set status = 'claimed',
         current_price = case when d.listing_type = 'sale'
                              then sale_price_now(d.original_price, d.radius_widened_at) end
    from recipients r
   where d.id = p_donation_id
     and r.id = p_recipient_id
     and d.status in ('posted', 'escalated')
     and d.expires_at > now()
     and st_dwithin(d.location, r.location, d.search_radius_m)
  returning d.current_price into v_price;  -- the post-update value: price at this moment (null for donations)

  if not found then
    raise exception 'not_available' using errcode = 'P0001';
  end if;

  insert into claims (donation_id, recipient_id, reserved_price)
  values (p_donation_id, p_recipient_id, v_price)
  returning * into v_claim;

  return v_claim;
end;
$$;

revoke execute on function sale_price_now(numeric, timestamptz) from public, anon, authenticated;
revoke execute on function claim_donation(uuid, uuid) from public, anon, authenticated;
