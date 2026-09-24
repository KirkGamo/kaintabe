-- 018: privacy, part 2 - apply only AFTER the web app that reads public_listings / /api/map is live.
-- The browser (anon key) can no longer read exact donation locations, donor names, claims,
-- or individuals' home locations. Exact details reach the right people only via /api/map.

drop policy "public read" on donations;
drop policy "public read" on claims;
alter publication supabase_realtime drop table donations, claims;

-- Recipients: partner orgs stay public (they're organizations); individuals never are
drop policy "public read" on recipients;
create policy "public read orgs" on recipients for select to anon, authenticated using (type = 'partner_org');


-- trigger-only function; Supabase grants functions to the API roles by default
revoke execute on function sync_public_listing() from anon, authenticated;
