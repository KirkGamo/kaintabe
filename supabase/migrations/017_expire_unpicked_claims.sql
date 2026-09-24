-- 017: a claimed listing that's never picked up must not stay "claimed" forever.
-- Food past its safe time isn't coming: one hour after expires_at (grace for someone who collected
-- it just in time and confirms a little late), an unconfirmed claimed listing closes as 'expired'.
-- Confirming after it closed is refused, so the impact numbers only count real pickups.

create or replace function expire_donations()
returns integer
language plpgsql
set search_path = public, extensions
as $$
declare
  v_count integer;
begin
  update donations
     set status = 'expired'
   where (status in ('posted', 'escalated') and expires_at <= now())
      or (status = 'claimed' and expires_at <= now() - interval '1 hour');
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

create or replace function confirm_pickup(p_claim_id uuid, p_photo_url text)
returns claims
language plpgsql
set search_path = public, extensions
as $$
declare
  v_claim claims;
begin
  update claims c
     set confirmed_at = now(), confirmation_photo_url = p_photo_url
    from donations d
   where c.id = p_claim_id and c.confirmed_at is null
     and d.id = c.donation_id and d.status = 'claimed'  -- not after the listing closed
  returning c.* into v_claim;

  if v_claim.id is null then
    raise exception 'not_confirmable' using errcode = 'P0001';
  end if;

  update donations
     set status = case when listing_type = 'sale' then 'sold' else 'completed' end
   where id = v_claim.donation_id;

  return v_claim;
end;
$$;

revoke execute on function expire_donations() from public, anon, authenticated;
revoke execute on function confirm_pickup(uuid, text) from public, anon, authenticated;
