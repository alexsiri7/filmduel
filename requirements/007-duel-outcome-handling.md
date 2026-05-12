---
id: "007"
title: "Duel outcome handling and film state transitions"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
Different outcomes (`a_wins`, `b_wins`, `a_only`, `b_only`, `neither`) have different implications for ELO and film visibility. The state machine needs to be precise.

## What
Five outcome types. `a_wins`/`b_wins`: update ELO for both, set both to Ranked. `a_only`/`b_only`: mark winner as Seen-unranked, loser as Unseen. `neither`: both → Unseen. `seen=false` films never appear in swipe or duel again. `next_action` (`duel`/`swipe`) included in every duel response.
