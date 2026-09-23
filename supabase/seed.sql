-- Demo seed: pre-onboarded Iloilo City recipients plus demo donors for the simulator.
-- Fixed UUIDs keep this re-runnable. Org names are fictional; coordinates are real districts.

insert into recipients (id, name, type, lat, lng, capacity, hours, service_radius_m, verified) values
  ('00000000-0000-0000-0000-00000000a001', 'Bayanihan Pantry Jaro',         'partner_org', 10.7245, 122.5570, '60 meals/day',  '7:00–20:00', 6000, true),
  ('00000000-0000-0000-0000-00000000a002', 'La Paz Community Kitchen',      'partner_org', 10.7128, 122.5700, '100 meals/day', '6:00–21:00', 6000, true),
  ('00000000-0000-0000-0000-00000000a003', 'City Proper Food Hub',          'partner_org', 10.6965, 122.5645, '150 meals/day', '24 hours',   8000, true),
  ('00000000-0000-0000-0000-00000000b001', 'Ana R. (Molo)',                 'individual',  10.6975, 122.5446, null, null, 3000, false),
  ('00000000-0000-0000-0000-00000000b002', 'Ben T. (Mandurriao)',           'individual',  10.7200, 122.5340, null, null, 3000, false)
on conflict (id) do nothing;

-- Demo donors (no Telegram chat) used by scripts/sim_post.py
insert into donors (id, name, type, lat, lng, pledged_at) values
  ('00000000-0000-0000-0000-00000000d001', 'Panaderia sa Mandurriao', 'business',  10.7141, 122.5519, now()),
  ('00000000-0000-0000-0000-00000000d002', 'Molo Carinderia',         'business',  10.6962, 122.5452, now()),
  ('00000000-0000-0000-0000-00000000d003', 'Household in Jaro',       'household', 10.7290, 122.5580, now())
on conflict (id) do nothing;
