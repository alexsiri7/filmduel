---
id: "004"
title: "ELO ranking system"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
Head-to-head comparisons produce a meaningful ranked list without asking users to assign explicit scores. ELO is the right model for this: it self-corrects over time and handles transitivity naturally.

## What
ELO with an uncertainty-aware K = 300/sqrt(battles+1), kept unrounded (rounded only for display). `elo` is NULL until `battles ≥ 1`. `seeded_elo` from imported Trakt ratings used as bootstrap value for the first duel only. ELO → Trakt rating mapping on a 1–10 scale.
