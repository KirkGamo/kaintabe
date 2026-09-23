-- 002: nearby_donations reads recipients.location, which anon can't select directly
-- (column grants hide it). The function is read-only, so let it run as its owner.
alter function nearby_donations(uuid) security definer;
