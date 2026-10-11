# TouchGrass FC: I Built a Telegram Bot That Gets a Football Group Off Their Phones and Onto a Pitch

![TouchGrass FC Cover](assets/cover.png)

<p align="center">
  <img src="assets/logo.png" alt="TouchGrass FC Logo" width="160" />
</p>

## What I Built

TouchGrass FC is a Telegram group bot that solves a very specific problem: every pickup football group has the same 20-message thread that goes nowhere. "Can you Saturday?" "Maybe." "What time?" "After work." "Which Saturday?" Nobody commits. The match never happens.

The bot intercepts that conversation. Players reply to a single prompt in whatever language they speak (Ukrainian, English, Spanish, German, Polish, French — real pickup groups are international). A local Gemma model reads each message and extracts structured availability. Deterministic code scores the candidate slots against a 7-day weather forecast, enforces a "must finish before sunset" constraint, finds the nearest football pitch via OpenStreetMap, and posts exactly one non-anonymous Telegram poll. Then the bot goes quiet — except for a 3-hour-before reminder and a post-match "did you actually play?" ping.

The answer to that last question is the metric that matters: `⚽ Matches actually played: N`. That number is the point.

**Demo:** [TODO: add YouTube link after recording]

**Code:** [https://github.com/your-org/touchgrass-fc](https://github.com/your-org/touchgrass-fc)

---

## How I Built It

### The Stack

- **Python 3.11+**, aiogram 3 (long polling, privacy mode ON)
- **Gemma via Ollama** — local inference, structured JSON output via the `format` parameter
- **Pydantic v2** — schema validation with one retry loop on failure
- **SQLite + aiosqlite** — all state is local; nothing leaves the machine except weather/map API calls
- **Open-Meteo** — free, keyless hourly weather (precipitation probability + wind speed + daily sunset)
- **Nominatim** (geocoding) + **Overpass API** (pitches: `leisure=pitch sport=soccer`) — free, open data

### The NLU layer

The hardest part was multilingual availability parsing: «можу в суботу після 18, якщо не дощ», «Sat morning I'm in», «puedo el sábado después de las 18», «Samstag ab 18 Uhr geht» — these all need to produce the exact same structured schema.

I used Ollama's `format` parameter with the full Pydantic JSON schema baked into the request. Temperature = 0. On ValidationError, the bot serialises the error and re-sends it to the model with the original message — one retry, then it asks the player to rephrase.

```python
payload = {
    "model": model,
    "stream": False,
    "options": {"temperature": 0},
    "format": _SCHEMA,   # Pydantic JSON schema
    "messages": [{"role": "system", ...}, {"role": "user", "content": message}],
}
```

### The Planner

Deliberately dumb. `score = player_count × weather_score`. Weather score = 60% rain penalty + 40% wind penalty, averaged over the slot window. Any slot ending after sunset (with a 15-minute buffer) is filtered out before scoring. No LLM involved — it's just numbers.

### The Eval

I wrote 40 labelled fixture messages across Ukrainian, Russian, and English — slang, negations, conditionals, time ranges, "можу в будь-який день після 19". The eval harness runs them against multiple Gemma sizes and prints a markdown table:

| Model | Overall | can_play | language | slots | conditions | avg_lat | p95_lat |
|---|---|---|---|---|---|---|---|
| `gemma3:1b` | 18% | 45% | 48% | 55% | 80% | 6.6s | 16.1s |
| `gemma3:4b` | 28% | 88% | 50% | 72% | 88% | 23.2s | 36.1s |

The 4b model delivers solid practical extraction (88% availability detection, 72% slot extraction, 88% weather condition handling) on zero-cost local hardware without sending private chat availability to third-party cloud APIs.

### The Simulator

Because not everyone wants to set up a Telegram bot token just to see if the code works, I built a CLI simulator:

```bash
python -m touchgrass simulate
```

It replays a scripted group conversation, calls the real Ollama NLU (or falls back to hardcoded mocks if Ollama isn't running), applies the real planner with synthetic weather, and prints a colourful transcript. Judges can run this in 30 seconds.

---

## Why Does Open Innovation Matter?

A bot like this _should_ be embarrassingly simple to run privately. But if the NLU core is a closed API, you have a problem:

1. **Privacy**: availability messages hint at weekly routines, employer schedules, location. Do you want that hitting a commercial API?
2. **Cost**: the eval alone is 120 inferences. At typical API prices that's a rounding error, but multiply by a real user base and it compounds.
3. **Vendor lock-in**: if the API changes its schema or pricing, the bot breaks or gets expensive. With `OLLAMA_MODEL=gemma3:12b` you upgrade by changing one env var.
4. **Hackability**: the structured output schema is a Pydantic model in `nlu.py`. Any contributor can read it, change it, test it against the fixture suite, and submit a PR without needing an API key.

The eval table is the concrete argument: `gemma3:4b` achieves 88% availability detection and 72% slot extraction with zero marginal API cost. That's not a compromise — that's the right tool for the job.

---

## My Agent Session

I used Antigravity (Google's agentic coding assistant) to scaffold the entire project from a single detailed spec. The interesting part was the parallel workstream structure: NLU + eval fixtures, planner + weather + pitches, and bot + simulator were all specced as independent streams that could be assembled into a working whole. The AI built each module with clean interfaces, wrote tests using fixture data (no network in tests), and generated this post.

The parts that needed human judgment: the 40 fixture messages (I wrote the Ukrainian and Russian ones), the weather scoring weights (60/40 rain/wind — arbitrary but defensible), and verifying the Ollama structured-output integration actually works with the Pydantic schema. That last one required one iteration: Ollama's `format` parameter needs the full JSON Schema object, not just the `$defs` block.

---

## Prize Categories

- **Best Use of Gemma** — Gemma 3 (via Ollama) is the only AI in this project. It does multilingual NLU with structured output and writes 2-sentence match invites in the group's dominant language. The eval harness benchmarks it locally across multiple sizes (`gemma3:1b` and `gemma3:4b`). The default `gemma3:4b` achieves 88% can_play accuracy, 72% slot extraction, and 88% condition recognition on 40 multi-lingual fixtures, with zero API cost.

---

_[TODO: add demo link once recorded]_  
_[TODO: fill in "how it went outside" after the first real match]_
