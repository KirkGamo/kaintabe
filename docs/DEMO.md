# KainTabe demo: run sheet

**Setup:** one presenter's phone runs the real prod bot (@KainTabe_bot). Your account switches roles with `/demo` in the chat. A laptop drives the projector and runs `scripts/demo.py`, which plays the other people: a partner org that claims and picks up your food, and donors that post food near you.

**Target length:** about 5½ minutes, plus Q&A.

All commands below run from the repo root on the laptop. `demo` is short for:

```sh
backend/.venv/Scripts/python scripts/demo.py
```

---

## How one phone plays everyone

- **Your account switches roles.** Send `/demo donor`, `/demo org` or `/demo individual` in the bot chat. You become only that role, and the others are set aside (not deleted).
- **Starting over as a new user:** `/demo fresh` sets aside every role, so `/start` shows the sign-up as a brand-new user would see it. `/demo all` brings every role back.
- **Only your chat can use `/demo`.** It's controlled by `DEMO_ADMIN_CHAT_ID` on Railway, and everyone else is told it's an unknown command.
- **The laptop plays everyone else.** A stand-in pantry claims your food and picks it up, and stand-in donors post food near you.

## The day before

- [ ] **Start from scratch.** Run `demo wipe` to see what would be deleted, then `demo wipe --yes`.
  - It deletes every listing, donor, org and individual except the seed.
  - It keeps the sample history, the 3 seeded pantries (stand-ins) and the stand-in donors.
  - **It can't be undone.**
- [ ] **Create your org once** on @KainTabe_bot. `/start` → *🏢 We're a community kitchen / org* → *➕ Register a new organization*.
  - Don't pick a listed pantry: `demo.py` uses those as stand-ins.
  - Choose 5 km and a location in Jaro.
- [ ] **Create your individual once.** `/demo fresh` → `/start` → *🙋 I need food* → a location in Jaro.
- [ ] **Leave your account new for the stage.** Send `/demo fresh` again. The donor is registered live on stage.
- [ ] **Check:** `demo status` shows your org and individual as *set aside*.
- [ ] **Rehearse the whole script once.** Start with `demo prepare`. After it, run `demo wipe --yes`, redo the three setup steps above, and end with `demo reset` (timers back to normal).
- [ ] **Record a backup video** of one full run: a screen recording of the phone plus the projector map. If the venue Wi-Fi or Telegram fails on stage, play it instead.
- [ ] **Take 2–3 good food photos** for the post (e.g. pandesal on a tray) and keep them on the phone.
- [ ] **Venue outside Iloilo?** Practise choosing the donor spot with 📎 → *Location* and searching "Jaro Plaza". The stand-in pantries are in Iloilo, so your venue's GPS spot would be out of their range.

## 15 minutes before

- [ ] **Networks:** the laptop is on a reliable network and the phone is on mobile data. Have a hotspot as plan B.
- [ ] **Prepare:** run `demo prepare`. It:
  - turns the demo timers on (1 minute instead of 10/60);
  - makes sure the sample history exists;
  - removes leftover stand-in listings;
  - prints your roles.
- [ ] **Phone:** send `/demo fresh`. This also wakes the backend, so the first reply on stage isn't slow. Notifications are on, not silent.
- [ ] **Projector tab 1:** https://appcon2026-team-triecode-kaintabe.vercel.app (public live map).
- [ ] **Projector tab 2:** the same URL with `#impact` (Impact tab).

---

## On stage

| # | Time | Who / where | What to do | What the audience sees | What to say |
|---|------|-------------|-----------|------------------------|-------------|
| 0 | 0:00 | Projector: map | Nothing yet | Live map of Iloilo | "A third of food is wasted while families nearby go hungry. The problem isn't supply, it's the last hour: surplus food expires before anyone knows it exists." |
| 1 | 0:30 | **Phone (new donor)** | `/start` → **🍱 I have food to share**. Type a name, pick *Business*, set the location, then **✅ I pledge**. | A 30-second sign-up in the chat | "A carinderia owner opens Telegram. No app to install, and there's a safety pledge up front." |
| 2 | 1:10 | **Phone (donor)** | Send a food photo. Answer food, quantity, *My saved location*, *good for 4 h*, the 3 safety questions, and **🎁 Donate free**. | "✅ Live now!" in the chat. **A pin appears on the projector map by itself.** | "Posting is a photo and a few taps. Three safety questions keep unsafe food out." |
| 3 | 2:00 | Projector: map | Point at the new pin and its circle | Approximate area, no name or photo | "The public map shows only a ~500 m area, never the donor's exact spot. Partner kitchens see exact details inside Telegram." |
| 4 | 2:15 | **Laptop** | `demo claim` | Phone buzzes: **"🎉 Claimed! … by <nearest pantry>"**. The pin turns claimed. | "The nearest partner kitchen claimed it in one tap. The donor knows someone's coming." |
| 5 | 2:40 | **Laptop** | `demo confirm` | Phone: **"✅ Picked up! … ≈ N meals. Salamat!"**. Switch the projector to **Impact**: the numbers tick up. | "Pickup is confirmed with a photo, so every number on this dashboard is a real handover." |
| 6 | 3:10 | **Phone, then laptop (org)** | Phone: `/demo org`. Laptop: `demo post`. Phone: tap **✅ Claim, free pickup** in the alert, then **🗺️ Open map**: *Your pickups* shows the exact pin. Confirm by sending a photo in the chat. | "You're now only the partner org". The alert arrives within seconds. The Mini App shows exact details. | "Now I'm the kitchen. Food posted 800 m away pings me directly. Inside Telegram, I'm identified automatically. No passwords." |
| 7 | 4:10 | **Phone, then laptop (individual)** | Phone: `/demo individual`. Laptop: `demo post --far`, then `demo escalate`. Phone: tap **🙋 I'll pick it up**. | The circle jumps to 8 km, and a **flash offer** arrives on the phone. | "If no kitchen claims it, the search widens every few minutes. At the limit, nearby individuals who signed up get a flash offer. Food doesn't sit." |
| 8 | 4:40 | Projector: map (optional) | `demo post --sale 150` | A sale pin whose price drops each tick | "Businesses can sell surplus at a falling price first. If nobody buys, it becomes a free donation." |
| 9 | 5:00 | Projector: Impact | — | Kg rescued, meals, CO₂e, chart | Close: "KainTabe: from surplus to someone's plate before it expires." |

**Honesty line (say it once, in scene 5):** "The earlier days on this chart are sample data. Today's pickups are live."

**Short on time?** Cut scene 8, then scene 7. Scenes 1–6 carry the story.

**After the demo:** run `demo reset`. It restores the real timers (10/60 min) and removes the stand-in listings. The sample history stays. Send `/demo all` to get every role back on your phone.

---

## If something goes wrong

| Symptom | Do this |
|---------|---------|
| The bot doesn't answer the photo | Send `/cancel`, then the photo again. Still nothing after 20 s: switch to the backup video. |
| `demo claim` says *no stand-in pantry is within range* | The listing is too far from the seeded pantries (they're in Jaro, La Paz and City Proper). Run `demo escalate`, then `demo claim`. |
| `demo claim` picked the wrong listing | Pass the id prefix shown by `demo status`, e.g. `demo claim 871a338a`. |
| No org alert after `demo post` | Did you send `/demo org` first? Run `demo status`: *you as org* must show your org on **@KainTabe_bot**. Orgs registered on the dev bot don't count on prod. |
| `/demo` says *I don't know that command* | `DEMO_ADMIN_CHAT_ID` on Railway is missing or wrong. It must be your chat id. |
| The bot seems stuck on an old question after switching roles | Send `/cancel`, then carry on. |
| No flash offer in scene 7 | Skip the scene; don't debug on stage. Later, check `demo status` for *paused* (`/demo individual` turns it back on). |
| The projector map looks frozen | Refresh the tab (updates are live, but a sleeping laptop can drop the connection). |
| Venue Wi-Fi is down | Use the phone hotspot for the laptop. If that fails, play the backup video. |

## Q&A crib

- **Food safety?** Every post passes a 3-question checklist, and any "no" blocks it. Donors pledge on sign-up. Pickups need a photo.
- **Why Telegram?** It's already on donors' phones. Posting is a photo and four taps, with no install. Orgs get the map inside Telegram as a Mini App.
- **Privacy?** The public map only shows ~500 m areas. Exact spots, names and photos are served only to the org whose range covers the listing, and only through Telegram-signed requests. The browser's database key can't read the raw tables.
- **Fake orgs?** Self-registered orgs are marked *pending review*. Real verification (registration papers, a barangay endorsement) is on the roadmap.
- **Money?** Sales are paid in person (cash or GCash) at pickup. KainTabe never touches payments.
- **What's next?** AI photo intake (built, waiting on API credits), verification, Filipino-language bot text, and partnerships with Iloilo LGUs and pantries.
