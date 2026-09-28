---
created: '2026-09-28'
github_issue: 666
id: '013'
status: idea
title: Adopt an OpenSpec specification as the statement of what FilmDuel should be
updated: '2026-09-28'
---

## Why

Requirement files record changes, not what the project should be. Auditing FilmDuel means replaying a change log across twelve coarse requirement files, a 58-entry requirements.yaml and several docs, and hand-kept status drifts: all twelve files here are recorded "done" and linked to one bookkeeping issue, even though some are only partly built. A spec per capability, changed only through spec-change pull requests, gives one document to audit against and lets Lachesis derive status from the work. This is the same move Lachesis made in its own requirement 030.

## What

The repository holds FilmDuel's specification in OpenSpec format under openspec/specs/, one file per capability: ai-suggestions, authentication, duels, elo-rating, feedback, platform, privacy-and-consent, rankings-and-export, rating-sync, swipe, title-pool and tournaments. CI validates it on every pull request and push to the default branch. From then on, work starts as spec changes, and the existing requirement files are superseded by the spec.

## Issues

- #666 — Add FilmDuel's OpenSpec specification and validate it in CI