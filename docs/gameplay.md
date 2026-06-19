# Gameplay

## Run

```bash
uv run aidnd            # terminal
uv run aidnd serve      # web UI at http://127.0.0.1:8000
```

Terminal special commands: `/look /inv /quests /stats /map /journal /help /quit`.
Everything else is free text.

## A short tour

```text
/look                                   # scene + environment affordances ("You can: rest, drink…")
Toblen, hello!                          # greeting (not a cold refusal)
Toblen, what's the word on the Redbrands?   # routed to dialogue, gated by trust
intimidate Toblen                       # uses the fear gate / a skill check
go to wyvern tor                        # wilderness travel: hours + risk
wait / wait / wait                      # a lull — the director may raise a random event
search                                  # react to a "you notice something" beat
```

Combat: `go to the hideout` → `go to the cave` → `attack Klarg`.

## Systems you can feel

- **World map & movement** — region sites are placed by compass direction from the graph;
  travel costs time and risk scaled by distance and danger. The web UI serves a live map at
  `/map` rendered from the player's actual `region_map()` (explored / hearsay / confirmed /
  debunked, with travel hours). Buy map info from NPCs — it can be **false or incomplete**,
  and the truth is revealed (and the liar flagged) when you visit.
- **Dialogue** — NPCs hold a relationship vector (affinity/trust/fear/respect). The same
  line yields different behavior by relationship: a stranger withholds, a trusted ally
  shares a real fact, a terrified NPC yields. No invented shared history on a first meeting.
- **Pacing** — when nothing interesting has happened for a while *and* the location allows,
  the chance of a context-appropriate random event rises: threat cues in the wild, social
  beats in town. Resting amplifies the lull.
- **Environment** — places advertise affordances (rest, drink, pray, shop…) surfaced in
  `look()`.

## Determinism

Same seed + same inputs reproduce the same world hash. Set the seed with `AIDND_SEED`:

```bash
AIDND_SEED=42 uv run aidnd
```
