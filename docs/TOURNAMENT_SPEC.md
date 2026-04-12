# FilmDuel — Tournament Mode Spec

## Overview

Tournament mode runs a structured bracket within a filtered subset of the user's **ranked** films (seen=true, battles≥1). Films the user hasn't seen are never included — a tournament is a celebration of your existing taste, not a discovery tool. Fixed bracket, visible progression, definitive champion.

Tournaments come in two flavours:

- **Manual** — user picks a filter (genre, decade, director) and bracket size. Standard seeding by ELO.
- **AI-curated** — user picks an optional pre-filter and bracket size. An LLM selects films and names a theme from within the filtered pool.

---

## Byes

Bracket sizes are powers of 2 (8, 16, 32, 64). The user's filtered ranked pool will rarely be exactly a power of 2. Byes handle the gap cleanly.

**Rule:** If the filtered pool has fewer films than the bracket size, top-seeded films receive byes in round 1 and advance automatically.

**Example:** 13 ranked horror films, 16-bracket selected.
- Seeds 1–3 get byes (advance automatically to round 2)
- Seeds 4–13 play round 1 (5 matches, producing 5 winners)
- Round 2 has 8 films: seeds 1, 2, 3 (byes) + 5 round-1 winners

**Minimum pool:** 4 ranked films matching the filter. Below 4, block creation and surface a message: "You need at least 4 ranked [genre] films to run a tournament. Keep dueling!"

**Maximum bracket:** Capped at the next power of 2 above the pool size. If the user has 20 ranked sci-fi films, the max bracket is 32 (with 12 byes). Don't offer brackets larger than 4× the pool size — too many byes kills the drama.

---

## Seeding

Standard tournament seeding: 1 vs last seed, 2 vs second-to-last, etc.

- Seed 1 = highest ELO in filtered pool
- Seed N = lowest ELO

For AI-curated tournaments, the LLM selects the films but seeding is still done by ELO after selection — the LLM doesn't control matchups.

---

## ELO Feedback

Tournament matches are real duels. Results feed back into the main ELO ranking exactly as regular duels do — same K-factor logic, same Trakt sync on completion. A tournament is not an isolated sandbox.

Store `duel_id` on each `tournament_match` row so the duel history is fully linked and there's no double-counting if a match is somehow replayed.

---

## Pre-filter + LLM Candidate Cap

For both manual and AI-curated tournaments, the candidate pool is derived as follows:

1. **Apply pre-filter** (optional): genre, decade (`1990s`, `2000s`, etc.), or director (Trakt person slug). If none selected, use all ranked films.
2. **Sort by ELO descending**, take top `bracket_size × 3` candidates.
   - 8-bracket → top 24
   - 16-bracket → top 48
   - 32-bracket → top 96
   - 64-bracket → top 192
3. For **manual** tournaments: seed the top `bracket_size` by ELO directly (with byes as needed).
4. For **AI-curated** tournaments: send the capped candidate list to the LLM (see below).

The cap keeps the LLM input bounded and focused. Sending "your top 48 horror films, find a psychological theme" is a better prompt than "all 200 ranked films."

If the filtered pool (before cap) is smaller than `bracket_size`, allow it — byes fill the gap. If it's smaller than 4, block creation.

---

## AI-Curated Tournament

### Flow

1. User selects optional pre-filter + bracket size
2. System builds candidate list (pre-filter → ELO sort → cap)
3. LLM call: receives candidate list, returns film selection + theme name
4. User sees preview: bracket name, tagline, selected films
5. User confirms or regenerates (up to 3 attempts)
6. Tournament begins

### LLM prompt

```
System:
You are a film curator for a movie ranking app. The user has 
ranked the following films through head-to-head duels. Your 
job is to select exactly {bracket_size} films for a themed 
tournament bracket and give it a compelling name.

Rules:
- Select ONLY films from the candidate list (use the id field)
- The theme should be specific and non-obvious — not just 
  "best films" or "top {genre}" but a genuine insight into 
  what connects these films
- The name should feel like a film festival programme title
- Return valid JSON only, no preamble

Return format:
{
  "name": "short evocative tournament name",
  "tagline": "one sentence that sells the theme",
  "theme_description": "2-3 sentences explaining what connects 
                        these films and why this theme emerged 
                        from the user's taste",
  "film_ids": ["uuid", "uuid", ...]   // exactly {bracket_size} ids
}

User:
Here are {count} ranked films{filter_context}. Select {bracket_size} 
for a themed tournament.

{candidate_list}
```

Where `{candidate_list}` is a JSON array:
```json
[
  {
    "id": "uuid",
    "title": "Mulholland Drive",
    "year": 2001,
    "genres": ["mystery", "drama"],
    "director": "David Lynch",
    "elo": 1380,
    "battles": 14
  },
  ...
]
```

And `{filter_context}` is something like ` (filtered to horror films, sorted by your ranking)` or empty string if no filter.

### LLM integration

Use the Anthropic API (`claude-sonnet-4-20250514`, max_tokens=500). This is a cheap, fast call — the candidate list is structured JSON, not prose, so tokens are efficient.

Store the full LLM response (name, tagline, theme_description) on the `tournaments` row. Show the `theme_description` to the user before they start playing — it should feel like a personalised insight, e.g. "You seem to gravitate toward films where the protagonist is trapped in a system they can't escape or fully understand. These 8 films are your most extreme examples of that."

### Regeneration

Allow up to 3 regenerations (different random seed / temperature). After 3, show a "Create manual tournament instead" fallback. Log regeneration count for analytics.

---

## Schema

```sql
create table tournaments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  name text not null,
  tagline text,
  theme_description text,           -- from LLM or null for manual
  filter_type text,                 -- 'genre' | 'decade' | 'director' | null
  filter_value text,                -- e.g. 'horror', '1990s', 'david-lynch' | null
  bracket_size integer not null,    -- 8 | 16 | 32 | 64
  status text not null default 'active',  -- 'active' | 'complete' | 'abandoned'
  champion_movie_id uuid references movies(id),
  is_ai_curated boolean not null default false,
  llm_response jsonb,               -- full raw LLM response for AI-curated tournaments
  created_at timestamptz default now(),
  completed_at timestamptz
);

create table tournament_matches (
  id uuid primary key default gen_random_uuid(),
  tournament_id uuid references tournaments(id) on delete cascade,
  round integer not null,           -- 1 = first round, increases toward final
  position integer not null,        -- position within round (1-indexed)
  movie_a_id uuid references movies(id),
  movie_b_id uuid references movies(id),
  winner_movie_id uuid references movies(id),
  is_bye boolean not null default false,  -- true = movie_a advances automatically
  duel_id uuid references duels(id),      -- linked duel record (null for byes)
  played_at timestamptz,
  unique(tournament_id, round, position)
);

create index on tournaments(user_id);
create index on tournaments(user_id, status);
create index on tournament_matches(tournament_id);
create index on tournament_matches(tournament_id, round);
```

---

## API Routes

```
POST /api/tournaments
     Body: { filter_type, filter_value, bracket_size, ai_curated: bool }
     Response: full tournament object with bracket (all matches pre-generated, 
               byes already resolved, future match slots empty)

GET  /api/tournaments
     List user's tournaments (active first, then completed)

GET  /api/tournaments/:id
     Full bracket state — all rounds, all matches, winners filled in so far

GET  /api/tournaments/:id/next
     Next unplayed match (skips byes, which are auto-resolved on creation)

POST /api/tournaments/:id/matches/:match_id
     Body: { winner_movie_id }
     Submits result, updates bracket, resolves any downstream byes,
     returns updated tournament state + next_match (or champion if final)

POST /api/tournaments/:id/regenerate
     AI-curated only. Re-runs LLM with same candidate pool. 
     Returns new tournament preview (not saved until confirmed).

POST /api/tournaments/:id/confirm
     Confirms a regenerated tournament preview and saves it.

DELETE /api/tournaments/:id
     Abandon (soft delete — set status='abandoned')
```

### Bracket generation (on POST /api/tournaments)

Pre-generate all match slots for all rounds on creation. Byes are resolved immediately — don't make the user play a bye. The bracket tree is complete from the start, with future match slots having null `movie_a_id` / `movie_b_id` until winners propagate.

---

## Frontend

### `/tournaments` — list + create

Active tournaments shown first with progress (e.g. "Round 2 of 4 · 3 matches remaining"). Completed tournaments show champion with poster. Create button opens a modal:

- Optional pre-filter: All · Genre · Decade · Director (pill selector)
- If genre/decade/director selected: show sub-picker
- Bracket size: auto-selected based on filtered pool size (show count: "You have 23 ranked horror films")
- Toggle: Standard / AI-curated
- For AI-curated: "Generate" button → loading state → preview card showing name, tagline, theme description, selected films
- Regenerate button (up to 3 times) + confirm

### `/tournaments/:id` — bracket + play

Visual bracket tree. Current match highlighted. Completed matches show winner's poster faded over loser's. Bye slots show a film advancing with a "bye" label.

Play area below the bracket: same two-card duel interface as the main duel screen but without the "only seen A / only seen B / neither" buttons — in a tournament both films are already ranked so those outcomes don't apply. Just: tap the winner.

Champion screen: full-width poster, tournament name, "Champion crowned" with confetti or similar celebration moment.

---

## Implementation Notes for Claude Code

- Generate all bracket slots on tournament creation — don't generate lazily round by round
- Byes propagate immediately on creation: if seed 1 has a bye, `tournament_matches` row for their round-1 slot has `is_bye=true` and `winner_movie_id = movie_a_id` already set, `played_at = now()`
- When a match result is submitted, check if the next match's opponent slot is now filled (both sides known) — if so, mark it ready. If the filled slot is a bye, auto-resolve it immediately server-side.
- Tournament matches use the same `POST /api/duels` endpoint internally — the tournament match submission calls the duel service and stores the returned `duel_id`
- LLM call is synchronous on tournament creation for AI-curated — it's fast enough (< 3s) and the user is waiting for the preview anyway. Don't background it.
- Store `llm_response` as raw JSONB — useful for debugging bad theme selections
- The `/api/tournaments/:id/next` endpoint should never return a bye match
