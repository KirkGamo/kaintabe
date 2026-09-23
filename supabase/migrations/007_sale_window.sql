-- 007: give the sale tier its own price window instead of reusing the auto-widen interval.
-- A real bakery needs longer than 10 minutes to sell; demo_mode.py shortens both timers together.

insert into app_config (key, value) values ('sale_window_minutes', 60)
on conflict (key) do nothing;

create or replace function sale_price_now(p_original numeric, p_since timestamptz)
returns numeric
language sql stable
set search_path = public, extensions
as $$
  select greatest(
    1,
    round(p_original * (1 - extract(epoch from (now() - p_since))
                            / ((select value from app_config where key = 'sale_window_minutes') * 60)))
  );
$$;

create or replace function decay_sale_prices()
returns integer
language plpgsql
set search_path = public, extensions
as $$
declare
  v_secs numeric := (select value from app_config where key = 'sale_window_minutes') * 60;
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
     set current_price = sale_price_now(original_price, radius_widened_at)
   where status = 'posted'
     and listing_type = 'sale'
     and current_price is distinct from sale_price_now(original_price, radius_widened_at);

  return v_converted;
end;
$$;
