-- 016: 015 revoked nearby_donations from anon/authenticated, but Postgres also grants EXECUTE on
-- every function to PUBLIC by default, so the browser key could still call it and read exact
-- listings. Revoke from PUBLIC too (the backend connects as the owner and is unaffected).
revoke execute on function nearby_donations(uuid) from public;
revoke execute on function sync_public_listing() from public;  -- trigger-only; never callable by the browser
