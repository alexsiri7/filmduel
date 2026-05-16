# Issue #182 Resolution Summary

**Issue**: [Security] FD-020: 30-day sliding JWT session with no revocation surface
**Status**: ✅ RESOLVED
**Resolved in**: Commit `48510ea` (PR #134, merged 2026-05-05)
**Investigation Date**: 2026-05-16

## Problems Addressed

### 1. JWT Expiry (30-day unbounded lifetime)
- **Status**: ✅ Fixed
- **Change**: Reduced from 720 hours (30 days) to 72 hours (3 days)
- **File**: `backend/routers/auth.py:43`

### 2. Unbounded Sliding Session
- **Status**: ✅ Fixed with 12-hour refresh throttle
- **Details**: Cookies only re-issued if token is older than 12 hours
- **File**: `backend/routers/auth.py:44,118-119`

### 3. No Server-Side Revocation
- **Status**: ✅ Fixed via `tokens_invalid_before` column
- **Capabilities**: 
  - Global logout (all devices)
  - Token revocation enforcement
  - Per-user token lifecycle management
- **Files**: 
  - Migration: `backend/migrations/versions/014_user_tokens_invalid_before.py`
  - Model: `backend/db_models.py:77-81`
  - Validation: `backend/routers/auth.py:107-115`
  - Endpoint: `backend/routers/auth.py:297-313`

## Validation

All tests pass:
- Backend tests: 274/274 ✅
- Backend lint: All checks ✅
- Frontend tests: 108/108 ✅
- Frontend build: Success ✅

## Next Steps

- Issue #182 can be closed as resolved
- All changes from PR #134 are in production
