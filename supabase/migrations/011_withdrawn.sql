-- 011: donors can take down a listing that's already gone ("Mark as gone" in /mylistings).
-- 'withdrawn' is terminal like 'expired': not in any active query, so it simply disappears from maps.

alter table donations drop constraint donations_status_check;
alter table donations add constraint donations_status_check
  check (status in ('posted', 'claimed', 'escalated', 'sold', 'completed', 'expired', 'withdrawn'));

-- Only the donor's own, still-unclaimed listing. Row-locking UPDATE, so it can't race a claim:
-- whichever commits first wins, the other gets not_withdrawable / not_available.
create function withdraw_donation(p_donation_id uuid, p_donor_id uuid)
returns donations
language plpgsql
set search_path = public, extensions
as $$
declare
  v_row donations;
begin
  update donations
     set status = 'withdrawn'
   where id = p_donation_id
     and donor_id = p_donor_id
     and status in ('posted', 'escalated')
  returning * into v_row;

  if v_row.id is null then
    raise exception 'not_withdrawable' using errcode = 'P0001';
  end if;
  return v_row;
end;
$$;

revoke execute on function withdraw_donation(uuid, uuid) from public, anon, authenticated;
