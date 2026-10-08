# Demo Storyboard — TouchGrass FC

**Target length:** 60–90 seconds  
**Format:** screen recording with terminal + optional phone screen mirroring

---

## Scene 1 — The Problem (0:00–0:10)

Show a mock Telegram group with the typical chaos:

```
Олексій:  можу в суботу
Maria:    Saturday works
Дмитро:   суботу не можу
Carlos:   Sunday morning?
Іванна:   в неділю вранці або суботу після 18
```

Caption: _"5 players, 3 languages, 0 agreement."_

---

## Scene 2 — /setlocation (0:10–0:20)

Type `/setlocation Kyiv` in the group.  
Bot replies: `📍 Location set to Kyiv (50.4501, 30.5234)`

Caption: _"One command. Now the bot knows where you play."_

---

## Scene 3 — /play (0:20–0:30)

Type `/play`.  
Bot posts the collection message: _"Reply to this message in your own words…"_

Players send replies (replay from `python -m touchgrass simulate` if recording terminal).  
Show the NLU parsing each reply in real-time (print `[NLU] { can_play: true, slots: [...] }`).

Caption: _"Ukrainian, Russian, English — Gemma reads them all."_

---

## Scene 4 — /plan (0:30–0:50)

Type `/plan` (or show the auto-trigger after 5 replies).

Terminal shows:
```
▶ Fetching weather forecast…
▶ Querying Overpass for pitches…
▶ Scoring 3 candidate slots…
✅ Best slot: Sunday 10:00–12:00 | 3 players | weather 91%
✅ Nearest pitch: Olimpiyskiy Training Ground
▶ Writing Gemma invite in Ukrainian…
```

Bot posts in the group:
- 2-sentence invite in Ukrainian
- Non-anonymous poll: ✅ In! / ❌ Out / 🤔 Maybe
- 📍 Location pin for the pitch

Caption: _"One poll. One pin. Done."_

---

## Scene 5 — Outside (0:50–1:10)

> **TODO:** Replace with actual footage of the match.

Show a football being kicked on a real pitch.  
Overlay: _"3h later, bot sends: ⚽ Reminder: match in 3 hours!"_  
Overlay: _"2h after match: Did you actually play? 👍"_  
Show `/played` command and bot response: _"🏆 Legendary. Logged."_

Caption: _"TouchGrass FC: gets you off the screen and onto the pitch."_

---

## Scene 6 — Stats (1:10–1:20)

Show `/stats` → `⚽ Matches actually played: 1`

Caption: _"Open-weight AI. Local data. Real grass."_

---

## Recording Tips

- Use `python -m touchgrass simulate` to generate the clean terminal output without needing a live bot token.
- Record at 1920×1080 or higher.
- Use [OBS Studio](https://obsproject.com/) or `wf-recorder` on Linux.
- Add subtle background music (Creative Commons licensed).
- Upload to YouTube as "unlisted" and add the link to POST.md.
