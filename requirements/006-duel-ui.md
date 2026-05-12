---
id: "006"
title: "Duel UI"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
The duel screen is the core user experience. It needs to feel fast and gamelike while surfacing enough information for the user to make a confident pick.

## What
Two tall poster cards side by side with a "vs" badge. Title, year, genres, ELO, and battle count displayed. Four action buttons: "I've seen both — pick a winner", "Only seen A", "Only seen B", "Haven't seen either". Next pair pre-fetched immediately on button tap. Swipe interstitial shown between duels when `next_action == "swipe"`.
