# Platform

## Purpose

FilmDuel runs as a single web service in front of a shared Postgres database. This capability holds the cross-cutting guarantees that keep it safe and available: request protections, rate limits, fail-fast configuration, error tracking and zero-downtime deploys.

## Requirements

### Requirement: State-changing requests must come from the app

Any request other than GET, HEAD or OPTIONS SHALL be accepted only when it carries the app's X-Requested-With header or an Origin or Referer in the allowed origins; otherwise it SHALL be refused, with "CSRF check failed: unexpected origin" for an unknown origin and "CSRF check failed: missing Origin/Referer" when none is present. The allowed origins SHALL never include a wildcard.

#### Scenario: Cross-site post
- GIVEN a signed-in user visiting https://evil.example
- WHEN that page posts to FilmDuel
- THEN the request is refused with "CSRF check failed: unexpected origin"

### Requirement: Cookies are hardened behind TLS

Session and sign-in cookies SHALL be httpOnly and SameSite=Lax. When cookies are secure they SHALL carry the Secure flag and the __Host- name prefix, and unprefixed cookies SHALL be ignored. Cookie security SHALL follow an explicit setting when given, else the base URL's scheme, and the service SHALL refuse to start on a known TLS-terminating host platform when neither makes cookies secure.

#### Scenario: Misconfigured Railway deploy
- GIVEN a deploy on Railway with no cookie setting and an http base URL
- WHEN the service starts
- THEN it refuses to start

### Requirement: Responses carry security headers

Every response, API or page, SHALL carry nosniff, frame denial, a referrer policy, a permissions policy and a content security policy allowing scripts and styles only from the app, images only from the app, TMDB and data URLs, and connections only to the app and error tracking; HSTS SHALL be sent whenever cookies are secure. Fonts SHALL be self-hosted.

#### Scenario: Page response
- GIVEN any page of the app
- WHEN it is served
- THEN its response carries the full set of security headers

### Requirement: Rate limits follow the user and hold under concurrency

Rate limits SHALL be counted per signed-in user, falling back to the real client address for anonymous requests, so changing networks does not reset them. When shared storage is configured, counters SHALL live there and survive deploys and replicas; without it on a hosted platform, the service SHALL warn at startup that limits are per process. Every quota that counts existing records SHALL hold under concurrent requests, so two simultaneous requests cannot both pass the cap.

#### Scenario: Two sessions
- GIVEN a user signed in on two devices
- WHEN both make requests to the same limited endpoint
- THEN both count against one limit

#### Scenario: Racing the cap
- GIVEN a user one tournament below the daily cap
- WHEN they send two create requests at the same instant
- THEN exactly one tournament is created

### Requirement: Provider requests cannot be redirected

Values taken from users or providers, such as usernames, SHALL be encoded before being placed in a provider API path, so that no value, including one containing "/" or "..", can change which endpoint is requested.

#### Scenario: Dot-segment username
- GIVEN a Trakt username of ".."
- WHEN the user's watch history is fetched
- THEN the request goes to that user's watch history path, not a parent path

### Requirement: Misconfiguration stops the service at startup

The service SHALL refuse to start when the database URL is missing or a placeholder, the session secret is shorter than 32 characters or a known placeholder, or a sign-in provider is configured without a valid token-encryption key. Startup checks SHALL report what is wrong without printing secret values.

#### Scenario: Placeholder secret
- GIVEN the session secret is the example placeholder
- WHEN the service starts
- THEN it refuses to start and names the problem

### Requirement: One service serves the app and the API

The same service SHALL serve the web app and the API: any non-API path SHALL return the app, paths escaping the static folder SHALL NOT be served, and a missing build SHALL be reported as unavailable. Interactive API docs SHALL be available only on localhost.

#### Scenario: Deep link
- GIVEN a user opening /rankings directly
- WHEN the page is requested
- THEN the app is returned and shows their rankings

### Requirement: Deploys are zero-downtime and errors are tracked

On start, the service SHALL answer its health check before running database migrations, SHALL retry migrations with backoff and SHALL stop if they ultimately fail. Unhandled errors, token refresh failures and sync failures SHALL be reported to error tracking when it is configured. Database connections SHALL NOT be exhausted by background work under normal load.

#### Scenario: Slow migration
- GIVEN a deploy whose migration takes three minutes
- WHEN the new instance starts
- THEN its health check passes during the migration and traffic switches only once it is up

#### Scenario: Background syncs under load
- GIVEN several users dueling with rating sync on
- WHEN their requests and background syncs run together
- THEN no request fails for want of a database connection
