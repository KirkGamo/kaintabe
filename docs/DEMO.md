# KainTabe demo: run sheet

**Setup:** one presenter's phone runs the real prod bot (@KainTabe_bot). A laptop drives the projector and runs `scripts/demo.py`, which plays the other people: a partner org that claims and picks up your food, and donors that post food near your org.

**Target length:** about 5 minutes, plus Q&A. Scenes 5 and 6 are optional. Drop them first if time is short.

All commands below run from the repo root on the laptop. `demo` is short for:

```sh
backend/.venv/Scripts/python scripts/demo.py
```

---

## The day before

- [ ] **Register all three roles on the prod bot** (@KainTabe_bot), from the presenter's phone. One Telegram account can hold all three.
  - [ ] **Donor:** already done (Lugawan ni Bro).
  - [ ] **Org:** `/start` → *🏢 We're a community kitchen / org* → *➕ Register a new organization*. Pick 5 km and put the location near the donor spot, in Jaro.
  - [ ] **Individual:** `/start` → 🙋 *I need food* (currently paused with /stop; this turns it back on).
- [ ] **Check the setup:** run `demo status`. All three roles should show, and the individual should not say *paused*.
- [ ] **Rehearse the whole script once** with `demo prepare` … `demo reset`.
- [ ] **Record a backup video** of one full run: a screen recording of the phone plus the projector map. If the venue Wi-Fi or Telegram fails on stage, play it instead.
- [ ] **Take 2–3 good food photos** for the post (e.g. pandesal on a tray) and keep them on the phone.

## 15 minutes before

- [ ] **Networks:** the laptop is on a reliable network and the phone is on mobile data. Have a hotspot as plan B.
- [ ] **Prepare:** run `demo prepare`. It:
  - turns the demo timers on (1 minute instead of 10/60);
  - makes sure the sample history exists;
  - removes leftover stand-in listings;
  - prints your roles.
- [ ] **Clear old real listings:** `demo status` should show no old listings of yours. If one is there, take it down on the phone: `/mylistings` → 🗑️.
- [ ] **Projector tab 1:** https://appcon2026-team-triecode-kaintabe.vercel.app (public live map).
- [ ] **Projector tab 2:** the same URL with `#impact` (Impact tab).
- [ ] **Phone:** open the bot chat. The photos are ready and notifications are on (not silent).
- [ ] **Wake the backend:** send `/mylistings` once so the first bot reply on stage isn't slow.

---

## On stage

| # | Time | Who / where | What to do | What the audience sees | What to say |
|---|------|-------------|-----------|------------------------|-------------|
| 0 | 0:00 | Projector: map | Nothing yet | Live map of Iloilo | "A third of food is wasted while families nearby go hungry. The problem isn't supply, it's the last hour: surplus food expires before anyone knows it exists." |
| 1 | 0:30 | **Phone (donor)** | Send a food photo to the bot. If it asks *what's this photo for?*, tap **📸 New food to share**. Answer food, quantity, *My saved location*, *good for 4 h*, the 3 safety questions, and **🎁 Donate free**. | "✅ Live now!" in the chat. **A pin appears on the projector map by itself.** | "A carinderia owner just messages Telegram. No app to install. Three safety questions keep unsafe food out." |
| 2 | 1:30 | Projector: map | Point at the new pin and its circle | Approximate area, no name or photo | "The public map shows only a ~500 m area, never the donor's exact spot. Partner kitchens see exact details inside Telegram." |
| 3 | 1:50 | **Laptop** | `demo claim` | Phone buzzes: **"🎉 Claimed! … by Bayanihan Pantry Jaro, 0.5 km away"**. The pin turns claimed. | "The nearest partner kitchen claimed it in one tap. The donor knows someone's coming." |
| 4 | 2:20 | **Laptop** | `demo confirm` | Phone: **"✅ Picked up! … ≈ N meals. Salamat!"**. Switch the projector to **Impact**: the numbers tick up. | "Pickup is confirmed with a photo, so every number on this dashboard is a real handover." |
| 5 | 2:50 | **Laptop, then phone (org)** | `demo post`, then on the phone tap **✅ Claim, free pickup** in the alert. Tap **🗺️ Map**: *Your pickups* shows the exact pin. Confirm by sending a photo in the chat (tap **✅ My pickup of …** if asked). | Org alert arrives within seconds. The Mini App shows exact details. | "Now I'm the kitchen. Food posted 800 m away pings me directly. Inside Telegram, I'm identified automatically. No passwords." |
| 6 | 3:50 | **Laptop, then phone (individual)** | `demo post --far` (2.6 km away). Point at the circle growing on the map every minute. Or skip ahead with `demo escalate`. | The radius circle widens. When it escalates, a **flash offer** arrives on the phone: tap **🙋 I'll pick it up**. (Your org gets an alert too once it widens; ignore it for this scene.) | "If no kitchen claims it, the search widens automatically. At the limit, nearby individuals who signed up get a flash offer. Food doesn't sit." |
| 7 | 4:30 | Projector: map (optional) | `demo post --sale 150` | A sale pin whose price drops each tick | "Businesses can sell surplus at a falling price first. If nobody buys, it becomes a free donation." |
| 8 | 4:50 | Projector: Impact | — | Kg rescued, meals, CO₂e, chart | Close: "KainTabe: from surplus to someone's plate before it expires." |

**Honesty line (say it once, in scene 4):** "The earlier days on this chart are sample data. Today's pickups are live."

**After the demo:** run `demo reset`. It restores the real timers (10/60 min) and removes the stand-in listings. The sample history stays.

---

## If something goes wrong

| Symptom | Do this |
|---------|---------|
| The bot doesn't answer the photo | Send `/cancel`, then the photo again. Still nothing after 20 s: switch to the backup video. |
| `demo claim` says *no stand-in pantry is within range* | The listing is too far from the seeded pantries (they're in Jaro, La Paz and City Proper). Run `demo escalate`, then `demo claim`. |
| `demo claim` picked the wrong listing | Pass the id prefix shown by `demo status`, e.g. `demo claim 871a338a`. |
| No org alert after `demo post` | Run `demo status`: does *you as org* show your org on **@KainTabe_bot**? Orgs registered on the dev bot don't count on prod. |
| No flash offer in scene 6 | The individual role is paused. Skip the scene; don't debug on stage. |
| The projector map looks frozen | Refresh the tab (updates are live, but a sleeping laptop can drop the connection). |
| Venue Wi-Fi is down | Use the phone hotspot for the laptop. If that fails, play the backup video. |

## Q&A crib

- **Food safety?** Every post passes a 3-question checklist, and any "no" blocks it. Donors pledge on sign-up. Pickups need a photo.
- **Why Telegram?** It's already on donors' phones. Posting is a photo and four taps, with no install. Orgs get the map inside Telegram as a Mini App.
- **Privacy?** The public map only shows ~500 m areas. Exact spots, names and photos are served only to the org whose range covers the listing, and only through Telegram-signed requests. The browser's database key can't read the raw tables.
- **Fake orgs?** Self-registered orgs are marked *pending review*. Real verification (registration papers, a barangay endorsement) is on the roadmap.
- **Money?** Sales are paid in person (cash or GCash) at pickup. KainTabe never touches payments.
- **What's next?** AI photo intake (built, waiting on API credits), verification, Filipino-language bot text, and partnerships with Iloilo LGUs and pantries.
