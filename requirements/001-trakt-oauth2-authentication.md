---
id: "001"
title: "Trakt OAuth2 authentication"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
FilmDuel builds on the user's existing watch history and ratings. Trakt is the canonical source of that data, so authentication via Trakt is the right entry point — no separate account setup needed.

## What
Full Trakt OAuth2 Authorization Code flow. JWT issued as httpOnly cookie. Token refresh before every Trakt API call if expiry is within 1 hour. Login, callback, and logout endpoints.
