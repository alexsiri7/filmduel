---
id: "010"
title: "Trakt rating sync"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
The user's Trakt profile is where their film data lives long-term. Syncing ELO-derived ratings back to Trakt (1–10 scale) keeps the two systems in sync.

## What
Fire-and-forget Trakt rating sync after every `a_wins` or `b_wins` outcome. ELO mapped to 1–10 scale. Retry once on 5xx; refresh token on 401. Failures logged to Sentry.
