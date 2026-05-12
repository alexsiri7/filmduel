---
id: "003"
title: "Swipe session (seen/unseen classification)"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
Before ranking films, users need to classify which ones they've seen. Swipe is a fast, friction-free way to build that classification without interrupting the ranking flow.

## What
10-film swipe session drawn from unknown (`seen IS NULL`) films, weighted by community rating band matching the user's median ELO. Tinder-style cards with swipe gesture (80px drag threshold) or tap buttons. Progress indicator. Summary screen on completion. Single bulk upsert for all 10 results.
