---
id: "012"
title: "Sentry error tracking"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
Deployed apps have bugs that only appear in production. Sentry catches exceptions at runtime and surfaces them with full context.

## What
Sentry FastAPI integration via `SENTRY_DSN` env var. Trakt sync failures, unhandled exceptions, and token refresh failures all captured.
