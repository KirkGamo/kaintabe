-- 022: listings start at 1 km and reach at most 5 km (was 2 km -> 8 km). 8 km is too far to travel
-- for a food pickup. Widening still doubles every widen period: 1 -> 2 -> 4 -> 5 km, then escalates.
-- Already set by hand on the live database; recorded here so a fresh setup matches.
update app_config set value = 1000 where key = 'radius_start_m';
update app_config set value = 5000 where key = 'radius_max_m';
