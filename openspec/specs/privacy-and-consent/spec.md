# Privacy and Consent

## Purpose

FilmDuel processes viewing preferences, which are personal data. It asks for informed consent before collecting any, tells users exactly what it keeps and for how long, and lets them take their data out or erase it at any time.

## Requirements

### Requirement: Consent to the current policy version gates data collection

After sign-in, a user SHALL accept the current privacy policy version before any provider data is imported or any data about them is recorded — swipes, duels, tournaments (creating, playing, abandoning), suggestion responses (dismiss, watchlist, seen), manual syncs and feedback reports; such requests from a user without consent SHALL be refused with "Privacy policy consent required". Accepting SHALL record the version and time. Consent to an unknown version SHALL be refused. When the policy version changes, the user SHALL be asked to consent again.

#### Scenario: First sign-in
- GIVEN a newly signed-in user who has not consented
- WHEN they open the app
- THEN they are asked to accept the privacy policy before anything else
- AND no library import has started

#### Scenario: Policy updated
- GIVEN a user who accepted version 2.0
- WHEN the current version becomes 2.1
- THEN the user is asked to consent again before continuing

#### Scenario: Duel without consent
- GIVEN a user who has not accepted the current policy
- WHEN they submit a duel
- THEN the request is refused with "Privacy policy consent required"

### Requirement: The policy is public and complete

The privacy policy SHALL be readable at /privacy without a session and without consent, and SHALL be linked from the sign-in page and the settings panel. It SHALL disclose the retention period of each kind of data the system keeps, and the consent prompt SHALL itemise, per AI feature, the film fields sent to the AI gateway, the candidate cap and the vendor, stating that raw ELO scores and account identifiers are never sent.

#### Scenario: Signed-out reader
- GIVEN a visitor with no session
- WHEN they open /privacy
- THEN the full policy is shown

#### Scenario: Retention is disclosed
- GIVEN duels are purged after 180 days
- WHEN a user reads the privacy policy
- THEN it states that duel history is kept for 180 days

### Requirement: Users can export all their data

A signed-in user SHALL be able to download, as a JSON file, every record held about them: profile, library, duels, tournaments, suggestions, swipe results, feedback reports and pool expansions. The export SHALL be built from explicit field lists that exclude provider tokens, SHALL name any section truncated by its size cap, SHALL be available whether or not the user has consented, and SHALL be limited to 10 exports per hour.

#### Scenario: Export after withdrawing consent
- GIVEN a user whose consent is not current
- WHEN they request their data export
- THEN they receive the JSON file

### Requirement: Users can delete their account

Deleting an account SHALL make a best-effort revocation of the user's provider tokens upstream, remove the user and every record that depends on them, end the session, and be limited to 3 attempts per hour.

#### Scenario: Account deleted
- GIVEN a user with duels, tournaments and feedback
- WHEN they delete their account
- THEN none of their records remain and their session ends

### Requirement: Data is kept only as long as disclosed

A daily purge SHALL reduce duels older than their retention window (default 180 days) to a minimal history of winner, loser and date kept until account deletion; delete swipe results and suggestions past 180 days; clear stored AI tournament responses past 180 days; delete feedback reports past 365 days; and clear screenshots past 90 days. Each window SHALL be configurable, and one purge failing SHALL NOT undo the others.

#### Scenario: Old swipes purged
- GIVEN a swipe result recorded 200 days ago
- WHEN the daily purge runs
- THEN that swipe result no longer exists

### Requirement: Abandoned sign-ups are deleted

Signing in creates an account and stores provider tokens before the user accepts the privacy policy. The daily purge SHALL delete accounts that never accepted the privacy policy once they are older than a configurable window (default 7 days), after a best-effort revocation of their provider tokens upstream. Accounts that accepted any policy version SHALL NOT be deleted by this purge.

#### Scenario: Abandoned sign-up purged
- GIVEN a user who signed in 8 days ago and never accepted the privacy policy
- WHEN the daily purge runs
- THEN that account no longer exists and its provider token has been revoked

### Requirement: Preference data stays out of logs and error reports

Log lines that pair a user with preference data (film ids, duel or swipe outcomes, ratings, taste profiles) SHALL be emitted only at debug level. Error reports SHALL carry no default personal data, and variables whose names suggest tokens, secrets or codes SHALL be filtered from them.

#### Scenario: Duel logged in production
- GIVEN production logging at INFO
- WHEN a user submits a duel
- THEN no log line at INFO or above names both the user and the films
