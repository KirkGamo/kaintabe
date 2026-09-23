-- 004: fields filled by AI photo intake.
alter table donations
  add column allergens       text[],                          -- e.g. {wheat,milk}; shown on the listing card
  add column ai_assisted     boolean not null default false,  -- details came from the photo (donor confirmed)
  add column suggested_price numeric;                         -- AI's fair discounted price (PHP), used by the sale tier
