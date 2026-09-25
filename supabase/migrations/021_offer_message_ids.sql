-- 021: remember which Telegram message carried each flash offer / org alert, so that once the food
-- is claimed (in the bot or on the map) those messages can be updated: "✅ It's yours" for the
-- claimer, "claimed by someone else" for everyone else, with the Claim / 🙋 buttons removed.
-- Before this, a claim made on the map left the offer's button live, and tapping it told the
-- claimer that "someone else" got it.

alter table flash_offers add column message_id bigint;
alter table org_alerts   add column message_id bigint;
