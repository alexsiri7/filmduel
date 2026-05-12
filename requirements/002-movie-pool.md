---
id: "002"
title: "Movie pool (Trakt + TMDB data ingestion)"
status: "done"
github_issue: 204
updated: 2026-05-12
---

## Why
The app needs a broad, pre-populated pool of films so there is always something to swipe or duel. Combining popular, trending, recommended, and user watch history covers both breadth and personalisation.

## What
Five Trakt data sources ingested and cached: popular (weekly), trending (weekly), recommended (daily), user watch history (hourly), user ratings (on login). TMDB poster images fetched and stored. Community rating stored on 0–100 scale. Shared `movies` table + per-user `user_movies` state.
