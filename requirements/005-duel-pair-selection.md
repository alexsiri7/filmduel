---
id: "005"
title: "Duel pair selection algorithm"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
Random pairings produce boring, uninformative duels. Good matchups should compare films of similar quality. New, unranked films should enter the pool quickly but not dominate.

## What
Weighted selection using `weight = 1/(battles+1)`. Every duel requires an anchor (a film with `battles ≥ 1`). Challenger constrained to the same ELO quality band as the anchor. Within-band ranked pairs: 70% close matches (ELO diff < 150), 30% wide matches (diff > 300). Anti-repeat guard.
