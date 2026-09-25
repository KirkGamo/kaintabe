# KainTabe demo: online pitch run sheet

**Format:** a live demo over a video call (Zoom, Google Meet or similar), shown by screen sharing. About 5½ minutes, plus Q&A.

**The idea in one line:** judges watch your Telegram and the live map side by side on your shared screen, while a script on the laptop plays the partner kitchen and the other donors.

All commands run from the repo root on the laptop. `demo` is short for:

```sh
backend/.venv/Scripts/python scripts/demo.py
```

---

## How it works on a video call

- **Telegram Desktop is your on-screen phone.** Log it into the same Telegram account as your phone. Every message syncs instantly, so judges see the bot chat in a clear, readable window instead of a tiny phone camera shot.
  - **Clicks happen on the laptop** so judges can follow your cursor: buttons, typing, commands, the 🗺️ Map.
  - **Use the phone only to share a location.** Telegram Desktop can't send locations, so the donor sign-up's location step is done on the phone. The chat on screen updates by itself.
- **One account plays every role.** Send `/demo donor`, `/demo org` or `/demo individual` to play only that role (the others are set aside, not deleted). `/demo fresh` makes you a brand-new user; `/demo all` brings every role back. Anyone can use `/demo`, but it only changes their own roles, so judges can try it too.
- **The script plays everyone else.** A stand-in pantry claims and picks up your food (`demo claim`, `demo confirm`), and stand-in donors post food near you (`demo post`).

## Screen layout

Share your **whole screen**, not a single window, so switching between Telegram and the browser stays in the share.

```
┌───────────────────────────┬─────────────────────────────────────────┐
│ Telegram Desktop          │ Browser: live map (tab 1), Impact (tab 2)│
│ only the KainTabe chat    │ kaintabe.vercel.app                      │
│ (~40% of the width)       │ (~60% of the width)                     │
└───────────────────────────┴─────────────────────────────────────────┘
Terminal for demo.py: on a second monitor that is NOT shared, or else a
small strip at the bottom (see "The terminal" below).
```

- **Readable at video quality:** Telegram Desktop → Settings → *Default interface scale* 125–150%. Browser zoom 125%. Video calls compress the picture, so small text turns to mush.
- **Only the bot chat on screen:** in Telegram Desktop, make a chat folder containing only @KainTabe_bot and select it, or collapse the chat list. Your other chats must not show.
- **The terminal:**
  - **Best:** a second monitor that you don't share. Type the commands there; judges only see the results.
  - **One screen only:** keep a small terminal strip visible with a large font, and be upfront about it: "this script plays the kitchen so I can show both sides with one account". Judges usually appreciate the honesty.
  - Either way, type each command once during setup so the **up-arrow** brings it back instantly on the call.

## The day before

- [ ] **Start from scratch.** Run `demo wipe` to see what would be deleted, then `demo wipe --yes`.
  - It deletes every listing, donor, org and individual except the seed.
  - It keeps the sample history, the 3 seeded pantries (stand-ins) and the stand-in donors.
  - **It can't be undone.**
  - If the database was emptied with `demo wipe --all`, first restore the seed and sample history: `backend/.venv/Scripts/python scripts/apply_sql.py --seed`, then `backend/.venv/Scripts/python scripts/seed_demo_history.py`.
- [ ] **Create your org once** on @KainTabe_bot. `/start` → *🏢 We're a community kitchen / org* → *➕ Register a new organization*.
  - Don't pick a listed pantry: `demo.py` uses those as stand-ins.
  - Choose 5 km and a location in Jaro.
- [ ] **Create your individual once.** `/demo fresh` → `/start` → *🙋 I need food* → pick a name → a location in Jaro.
- [ ] **Leave your account new for the pitch.** Send `/demo fresh` again. The donor is registered live during the demo.
- [ ] **Check:** `demo status` shows your org and individual as *set aside*.
- [ ] **Install Telegram Desktop** and log in with the same account. Set up the chat folder and the scale.
- [ ] **Do a full rehearsal on a real call.** Start a meeting with a teammate, share your screen and run the whole script while they watch.
  - Ask whether the text is readable and whether the map updates show up. They can take a minute to reach a viewer.
  - Start with `demo prepare`. After it, run `demo wipe --yes`, redo the three setup steps above, and end with `demo reset` (timers back to normal).
- [ ] **Record a backup video** of one full run, with the same screen layout and your voice-over. If the call, Telegram or the internet fails mid-pitch, share and play it (turn on *share computer audio*).
- [ ] **Pick 2–3 food photos** (e.g. pandesal on a tray) and put them in a folder you can drag from.
- [ ] **Not in Iloilo?** The stand-in pantries are in Iloilo, so a sign-up location from elsewhere is out of their range. On the phone, use 📎 → *Location* and search "Jaro Plaza" instead of your GPS spot. Practise it once.

## 15 minutes before

- [ ] **Internet:** cable, or sit close to the router. Close cloud sync, downloads and other video apps. Keep a phone hotspot ready as plan B.
- [ ] **Silence everything:** Windows *Do not disturb* on. Quit Slack, Messenger and email. Mute the phone, but keep Telegram notifications visible in Telegram Desktop; the message popping into the chat is the moment you want judges to see.
- [ ] **Prepare:** run `demo prepare`. It:
  - turns the demo timers on (1 minute instead of 10/60);
  - makes sure the sample history exists;
  - removes leftover stand-in listings;
  - prints your roles.
- [ ] **Telegram:** send `/demo fresh`. This also wakes the backend, so the first reply during the pitch isn't slow. Scroll the chat to the bottom.
- [ ] **Browser tab 1:** https://kaintabe.vercel.app (public live map). Hide the bookmarks bar and close other tabs.
- [ ] **Browser tab 2:** the same URL with `#impact` (Impact tab).
- [ ] **Terminal:** type `demo claim`, `demo confirm`, `demo post`, `demo post --far`, `demo escalate` and `demo post --sale 150` once each, then delete the lines, so they're in the history.
- [ ] **Links ready to paste into the meeting chat at the end:** the map URL, `t.me/KainTabe_bot` and the GitHub repo.
- [ ] **Backup video:** open in a player, paused at 0:00.

---

## During the pitch

| # | Time | On screen | What to do | What judges see | What to say |
|---|------|-----------|-----------|-----------------|-------------|
| 0 | 0:00 | Map | Nothing yet | Live map of Iloilo | "A third of food is wasted while families nearby go hungry. The problem isn't supply, it's the last hour: surplus food expires before anyone knows it exists." |
| 1 | 0:30 | Telegram | Click `/start` → **🍱 I have food to share**. Type a name, pick *Business*. **On the phone**, share the location. Back on the laptop, click **✅ I pledge**. | The intro (live totals, "How it works" in 3 steps), then a 30-second sign-up | "A carinderia owner opens Telegram. No app to install: the bot explains itself, and there's a safety pledge up front." |
| 2 | 1:10 | Telegram + map | Drag a food photo into the chat. Answer food, quantity, *My saved location*, *good for 4 h*, the 3 safety questions, and **🎁 Donate free**. | "✅ Live now!" in the chat, and **a pin appears on the map by itself** | "Posting is a photo and a few taps. Three safety questions keep unsafe food out." |
| 3 | 2:00 | Map | Hover over the new pin and its circle | Approximate area, no name or photo | "The public map shows only a ~500 m area, never the donor's exact spot. Partner kitchens see exact details inside Telegram." |
| 4 | 2:15 | Telegram + map | Terminal: `demo claim` | **"🎉 Claimed! … by ‹nearest pantry›"** arrives, and the pin turns claimed | "The nearest partner kitchen claimed it in one tap. The donor knows someone's coming." |
| 5 | 2:40 | Telegram, then Impact | Terminal: `demo confirm`. Then switch to the **Impact** tab. | **"✅ Picked up! … ≈ N meals. Salamat!"**, then the numbers tick up | "Pickup is confirmed with a photo, so every number on this dashboard is a real handover." |
| 6 | 3:10 | Telegram | Send `/demo org`. Terminal: `demo post`. Click **✅ Claim, free pickup** in the alert, then **🗺️ Open map**: *Your pickups* shows the exact pin. Close the map and drag a photo into the chat to confirm. | "You're now only the partner org". The alert arrives within seconds, and the Mini App shows exact details. | "Now I'm the kitchen. Food posted 800 m away pings me directly. Inside Telegram I'm identified automatically, so there are no passwords." |
| 7 | 4:10 | Telegram + map | Send `/demo individual`. Terminal: `demo post --far`, then `demo escalate`. Click **🙋 I'll pick it up**. | The circle jumps to its maximum reach (5 km), and a **flash offer** arrives | "If no kitchen claims it, the search widens every few minutes. At the limit, nearby individuals who signed up get a flash offer. Food doesn't sit." |
| 8 | 4:40 | Map (optional) | Terminal: `demo post --sale 150` | A sale pin whose price drops each tick | "Businesses can sell surplus at a falling price first. If nobody buys, it becomes a free donation." |
| 9 | 5:00 | Impact | — | Kg rescued, meals, CO₂e, chart | Close: "KainTabe: from surplus to someone's plate before it expires." Paste the links into the meeting chat. |

**Honesty line (say it once, in scene 5):** "The earlier days on this chart are sample data. Today's pickups are live."

**Keep talking while things load.** On a call, a silent pause of even 3 seconds feels long. Each scene's line is written to fill the wait before the next message or pin arrives.

**Short on time?** Cut scene 8, then scene 7. Scenes 1–6 carry the story.

**Invite judges to try it (Q&A):** "The link to the bot is in the chat. Send it a photo, or type /demo to try the kitchen or neighbor side." Their posts appear on the live map. After the pitch, `demo wipe` shows what to clean up.

**After the pitch:** run `demo reset`. It restores the real timers (10/60 min) and removes the stand-in listings. The sample history stays. Send `/demo all` to get every role back.

---

## If something goes wrong

| Symptom | Do this |
|---------|---------|
| The bot doesn't answer | Send `/cancel`, then try again. Still nothing after 20 s: "Let me show you a recording of the same flow", then share the backup video. |
| A dragged photo arrives as a file, not a photo | In the send dialog, tick *Compress image* (or *Send as photo*). The bot only reads photos. |
| Judges say the map or text is blurry | Zoom the browser in (Ctrl +) and carry on. Don't restart the share. |
| The map doesn't update on the judges' side | Refresh the tab. Updates are live but can take a moment to reach a viewer. |
| `demo claim` says *no stand-in pantry is within range* | The listing is too far from the seeded pantries (they're in Jaro, La Paz and City Proper). Run `demo escalate`, then `demo claim`. |
| `demo claim` picked the wrong listing | Pass the id prefix shown by `demo status`, e.g. `demo claim 871a338a`. |
| No org alert after `demo post` | Did you send `/demo org` first? Run `demo status`: *you as org* must show your org on **@KainTabe_bot**. |
| The bot seems stuck on an old question after switching roles | Send `/cancel`, then carry on. |
| No flash offer in scene 7 | Skip the scene; don't debug live. Later, check `demo status` for *paused* (`/demo individual` turns it back on). |
| Your internet drops | Switch to the phone hotspot and rejoin the call. If you can't rejoin quickly, a teammate in the call shares the backup video. |

## Q&A crib

- **Food safety?** Every post passes a 3-question checklist, and any "no" blocks it. Donors pledge on sign-up. Pickups need a photo.
- **Why Telegram?** It's already on donors' phones. Posting is a photo and four taps, with no install. Orgs get the map inside Telegram as a Mini App.
- **Privacy?** The public map only shows ~500 m areas. Exact spots, names and photos are served only to the org whose range covers the listing, and only through Telegram-signed requests. The browser's database key can't read the raw tables.
- **Fake orgs?** Self-registered orgs are marked *pending review*. Real verification (registration papers, a barangay endorsement) is on the roadmap.
- **Money?** Sales are paid in person (cash or GCash) at pickup. KainTabe never touches payments.
- **Was that real?** Yes: the bot, map and database are live in production. A script played the partner kitchen so one person could show every side; judges can try the bot themselves from the link in the chat.
- **What's next?** AI photo intake (built, waiting on API credits), verification, Filipino-language bot text, and partnerships with Iloilo LGUs and pantries.
