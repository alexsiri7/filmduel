# Authentication

## Purpose

FilmDuel builds on the watch history and ratings a user already keeps with a tracking service, so signing in with that service is the only way in. There is no separate FilmDuel account to create, and sessions are short-lived, revocable and never expose provider credentials.

## Requirements

### Requirement: Sign in with Trakt

A user SHALL sign in with their Trakt account through the OAuth2 Authorization Code flow with PKCE and a random state value. A callback whose state does not match the one issued SHALL be rejected. A successful callback SHALL create or update the user and start a session, then return the user to the app. The user SHALL be identified by Trakt's immutable account id, never by the username or slug, which can change.

#### Scenario: First sign-in
- GIVEN a visitor with a Trakt account and no FilmDuel user
- WHEN they sign in with Trakt and approve access
- THEN a FilmDuel user is created for that Trakt account
- AND they arrive in the app with an active session

#### Scenario: Forged callback
- GIVEN a sign-in was started with state S
- WHEN the callback arrives carrying a different state
- THEN the sign-in is refused and no session is created

#### Scenario: Renamed Trakt account
- GIVEN a FilmDuel user whose Trakt username was later changed, and a different person who has since taken the old username
- WHEN each signs in with Trakt
- THEN the original owner reaches their existing account
- AND the other person does not

### Requirement: Sign in with SIMKL as an optional provider

While a SIMKL application is configured, a user SHALL be able to sign in with SIMKL instead of, or in addition to, Trakt, through the same flow and protections. A user who signed in only with SIMKL SHALL have no Trakt identity. When no SIMKL application is configured, SIMKL sign-in SHALL NOT be offered.

#### Scenario: SIMKL-only user
- GIVEN SIMKL is configured
- WHEN a visitor signs in with SIMKL only
- THEN a user exists with a SIMKL identity and no Trakt identity

#### Scenario: SIMKL not configured
- GIVEN no SIMKL application is configured
- WHEN a visitor requests SIMKL sign-in
- THEN the request is refused

### Requirement: Sessions are bounded and sliding

A session SHALL be carried in an httpOnly cookie holding a signed token. Each token SHALL be valid for at most 72 hours, SHALL be re-issued at most once per 12 hours of activity, and no session SHALL outlive 30 days from the original sign-in regardless of activity.

#### Scenario: Active user
- GIVEN a session whose token was issued 13 hours ago
- WHEN the user makes a request
- THEN a fresh session cookie is issued carrying the original sign-in time

#### Scenario: Thirty-day cap
- GIVEN a session whose original sign-in was 31 days ago
- WHEN the user makes a request
- THEN the request is rejected as unauthenticated and the cookie is cleared

### Requirement: Logout revokes every session

Logging out SHALL invalidate every session the user holds on any device, not only the current cookie.

#### Scenario: Logout on one device
- GIVEN a user signed in on a phone and a laptop
- WHEN they log out on the laptop
- THEN the phone's next request is rejected as a revoked session

### Requirement: Provider tokens are protected and kept fresh

Provider access and refresh tokens SHALL be encrypted at rest with a key independent of the session-signing key, and SHALL never appear in any API response. Before calling Trakt, the system SHALL refresh a token that expires within one hour and persist the result. Concurrent refreshes for one user SHALL NOT race.

#### Scenario: Token about to expire
- GIVEN a Trakt token expiring in 30 minutes
- WHEN the system is about to call Trakt for that user
- THEN it refreshes the token first and stores the new token and expiry

#### Scenario: Profile response
- GIVEN a user with Trakt and SIMKL tokens stored
- WHEN they request their profile
- THEN the response contains no token or token expiry under any key
