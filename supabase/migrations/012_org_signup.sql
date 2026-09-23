-- 012: partner orgs sign up (or link a seeded org) through the Telegram bot.
-- Self-declared for the hackathon: new/linked orgs show as 'pending_review' on the map.
-- Real verification (registration lookup, local endorsement) is a roadmap item.

alter table recipients
  add column org_kind      text check (org_kind in ('community_kitchen', 'shelter', 'food_bank', 'pantry')),
  add column review_status text not null default 'approved'
                           check (review_status in ('approved', 'pending_review'));

-- The browser may show these two (never the Telegram chat id)
grant select (org_kind, review_status) on recipients to anon, authenticated;
