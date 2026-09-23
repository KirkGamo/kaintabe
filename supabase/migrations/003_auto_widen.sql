-- 003: auto-widen radius, escalation, and expiry, driven by pg_cron.
--   posted listing unclaimed for widen_after_minutes since its last widening → radius doubles (capped)
--   posted at max radius for another interval → 'escalated' (still claimable; flash-offer hook)
--   posted/escalated past expires_at → 'expired'

create function widen_unclaimed()
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
     and expires_at > now()
     and search_radius_m < v_max
     and radius_widened_at <= now() - v_interval;
  get diagnostics v_widened = row_count;

  update donations
     set status = 'escalated'
   where status = 'posted'
     and expires_at > now()
     and search_radius_m >= v_max
     and radius_widened_at <= now() - v_interval;
  get diagnostics v_escalated = row_count;

  return v_widened + v_escalated;
end;
$$;

create function expire_donations()
returns integer
language plpgsql
set search_path = public, extensions
as $$
declare
  v_count integer;
begin
  update donations
     set status = 'expired'
   where status in ('posted', 'escalated')
     and expires_at <= now();
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

-- One scheduled entry point; later tiers (price decay) hook in here too.
create function kaintabe_tick()
returns void
language plpgsql
set search_path = public, extensions
as $$
begin
  perform expire_donations();
  perform widen_unclaimed();
end;
$$;

revoke execute on function widen_unclaimed() from public, anon, authenticated;
revoke execute on function expire_donations() from public, anon, authenticated;
revoke execute on function kaintabe_tick() from public, anon, authenticated;

-- pg_cron 1.5+ supports sub-minute schedules; 15 s keeps the demo snappy and costs nothing.
select cron.schedule('kaintabe-tick', '15 seconds', 'select public.kaintabe_tick()');
