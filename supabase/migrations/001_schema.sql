-- 001: core schema: donors, recipients, donations, claims, config, storage, RPCs.
-- Points are stored as lat/lng (easy to insert and to read in Realtime payloads).
-- `location` is a generated geography column used by the PostGIS queries.

create extension if not exists postgis with schema extensions;

-- Tunables (demo mode can shorten timers without code changes)
create table app_config (
  key   text primary key,
  value numeric not null
);

insert into app_config (key, value) values
  ('radius_start_m', 2000),
  ('radius_max_m', 8000),
  ('widen_after_minutes', 10);

create table donors (
  id               uuid primary key default gen_random_uuid(),
  telegram_chat_id bigint unique,
  name             text not null,
  type             text not null check (type in ('business', 'household')),
  lat              double precision,
  lng              double precision,
  location         extensions.geography(Point, 4326) generated always as (
                     extensions.st_setsrid(extensions.st_makepoint(lng, lat), 4326)::extensions.geography
                   ) stored,
  pledged_at       timestamptz,
  created_at       timestamptz not null default now()
);

create table recipients (
  id               uuid primary key default gen_random_uuid(),
  name             text not null,
  type             text not null check (type in ('partner_org', 'individual')),
  lat              double precision not null,
  lng              double precision not null,
  location         extensions.geography(Point, 4326) generated always as (
                     extensions.st_setsrid(extensions.st_makepoint(lng, lat), 4326)::extensions.geography
                   ) stored,
  capacity         text,
  hours            text,
  service_radius_m integer not null default 5000,
  verified         boolean not null default false,
  telegram_chat_id bigint,
  created_at       timestamptz not null default now()
);

create table donations (
  id                uuid primary key default gen_random_uuid(),
  donor_id          uuid not null references donors(id),
  donor_name        text not null,  -- denormalized so the public map never reads donors
  photo_url         text,
  food_type         text not null,
  quantity          text not null,
  est_kg            numeric,
  lat               double precision not null,
  lng               double precision not null,
  location          extensions.geography(Point, 4326) generated always as (
                      extensions.st_setsrid(extensions.st_makepoint(lng, lat), 4326)::extensions.geography
                    ) stored,
  safety_checklist  jsonb,
  listing_type      text not null default 'donation' check (listing_type in ('donation', 'sale')),
  original_price    numeric,
  current_price     numeric,
  expires_at        timestamptz not null,
  search_radius_m   integer not null default 2000,
  radius_widened_at timestamptz not null default now(),
  status            text not null default 'posted'
                      check (status in ('posted', 'claimed', 'escalated', 'sold', 'completed', 'expired')),
  created_at        timestamptz not null default now()
);

create index donations_location_idx on donations using gist (location);
create index donations_status_idx on donations (status);
create index recipients_location_idx on recipients using gist (location);

create table claims (
  id                     uuid primary key default gen_random_uuid(),
  donation_id            uuid not null unique references donations(id),
  recipient_id           uuid not null references recipients(id),
  claimed_at             timestamptz not null default now(),
  confirmed_at           timestamptz,
  confirmation_photo_url text
);

-- ---------------------------------------------------------------------------
-- Access: the browser (anon key) is read-only; all writes go through the backend.
-- ---------------------------------------------------------------------------
alter table app_config enable row level security;
alter table donors     enable row level security;
alter table recipients enable row level security;
alter table donations  enable row level security;
alter table claims     enable row level security;

create policy "public read" on recipients for select to anon, authenticated using (true);
create policy "public read" on donations  for select to anon, authenticated using (true);
create policy "public read" on claims     for select to anon, authenticated using (true);
create policy "public read" on app_config for select to anon, authenticated using (true);
-- donors: no anon policy (holds Telegram chat ids)

-- Hide recipients' Telegram chat ids from the browser
revoke select on recipients from anon, authenticated;
grant select (id, name, type, lat, lng, capacity, hours, service_radius_m, verified, created_at)
  on recipients to anon, authenticated;

-- Realtime for the live map
alter publication supabase_realtime add table donations, claims;

-- Storage buckets (public read; uploads use the service role key)
insert into storage.buckets (id, name, public) values
  ('donation-photos', 'donation-photos', true),
  ('pickup-photos', 'pickup-photos', true)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- RPCs
-- ---------------------------------------------------------------------------

-- Open listings whose current search radius reaches this recipient, nearest first.
create function nearby_donations(p_recipient_id uuid)
returns table (
  id uuid, donor_name text, photo_url text, food_type text, quantity text, est_kg numeric,
  lat double precision, lng double precision, listing_type text, current_price numeric,
  expires_at timestamptz, search_radius_m integer, status text, created_at timestamptz,
  distance_m double precision
)
language sql stable
set search_path = public, extensions
as $$
  select d.id, d.donor_name, d.photo_url, d.food_type, d.quantity, d.est_kg,
         d.lat, d.lng, d.listing_type, d.current_price,
         d.expires_at, d.search_radius_m, d.status, d.created_at,
         st_distance(d.location, r.location) as distance_m
  from donations d
  join recipients r on r.id = p_recipient_id
  where d.status in ('posted', 'escalated')
    and d.expires_at > now()
    and st_dwithin(d.location, r.location, d.search_radius_m)
  order by distance_m;
$$;

-- Atomic one-tap claim. Only one caller can win: the UPDATE row-locks the donation
-- and re-checks status. Raises 'not_available' for everyone else.
create function claim_donation(p_donation_id uuid, p_recipient_id uuid)
returns claims
language plpgsql
set search_path = public, extensions
as $$
declare
  v_claim claims;
begin
  update donations d
     set status = 'claimed'
    from recipients r
   where d.id = p_donation_id
     and r.id = p_recipient_id
     and d.status in ('posted', 'escalated')
     and d.expires_at > now()
     and st_dwithin(d.location, r.location, d.search_radius_m);

  if not found then
    raise exception 'not_available' using errcode = 'P0001';
  end if;

  insert into claims (donation_id, recipient_id)
  values (p_donation_id, p_recipient_id)
  returning * into v_claim;

  return v_claim;
end;
$$;

-- Pickup confirmation with photo. Sale listings end as 'sold', donations as 'completed'.
create function confirm_pickup(p_claim_id uuid, p_photo_url text)
returns claims
language plpgsql
set search_path = public, extensions
as $$
declare
  v_claim claims;
begin
  update claims
     set confirmed_at = now(), confirmation_photo_url = p_photo_url
   where id = p_claim_id and confirmed_at is null
  returning * into v_claim;

  if v_claim.id is null then
    raise exception 'not_confirmable' using errcode = 'P0001';
  end if;

  update donations
     set status = case when listing_type = 'sale' then 'sold' else 'completed' end
   where id = v_claim.donation_id;

  return v_claim;
end;
$$;

-- Browser may read nearby listings; state changes are backend-only.
revoke execute on function claim_donation(uuid, uuid) from public, anon, authenticated;
revoke execute on function confirm_pickup(uuid, text) from public, anon, authenticated;
grant execute on function nearby_donations(uuid) to anon, authenticated;
