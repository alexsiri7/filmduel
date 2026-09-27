---
id: "005"
title: "Duel pair selection algorithm"
status: "done"
github_issue: 204
updated: 2026-09-27
---

## Why
Every seen film should keep moving into duels, and every duel should be close enough to be informative. Random pairings produce boring, uninformative duels, and a selection that leaves films un-dueled never ranks them.

## What
The anchor is a seen film with the fewest battles across all of the user's seen films (no cap), ties broken at random. The challenger is a random pick from the 5 seen films closest to the anchor in effective ELO (`elo`, else the seeded/default starting ELO). Anti-repeat guard: the anchor's partner from the last pair is skipped unless it is the only option. No weighting, quality bands, or wide-match branch.

Revised by #650 (was: `1/(battles+1)` weighting, ranked-only anchor, band-matched challenger with a 70/30 close/wide split).
