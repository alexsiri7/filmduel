---
id: "009"
title: "Letterboxd CSV export"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
Letterboxd is the social layer many film fans use. Exporting rankings keeps the data portable and useful outside the app.

## What
`GET /api/rankings/export/csv` returns a Letterboxd-compatible CSV of ranked films. Floating export button on the Rankings page.
