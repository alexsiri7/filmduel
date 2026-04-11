-- Add Trakt token expiry tracking to the users table.
-- Run this in the Supabase SQL editor after 001_initial_schema.sql.

alter table users add column if not exists trakt_token_expires_at timestamptz;
