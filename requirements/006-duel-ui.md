---
id: "006"
title: "Duel UI"
status: "done"
github_issue: 204
updated: 2026-09-27
---

## Why
The duel screen is the core user experience. It needs to feel fast and gamelike while surfacing enough information for the user to make a confident pick.

## What
Two tall poster cards side by side with a "vs" badge. Title, year, genres, ELO, and battle count displayed. Tapping a card picks it as the winner. Three secondary buttons below — "Only seen {A}", "Only seen {B}", "Haven't seen either" — record the pair without changing ratings. Next pair pre-fetched immediately on button tap. Swipe interstitial shown between duels when `next_action == "swipe"`.
