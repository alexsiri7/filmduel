# Feedback

## Purpose

Users report problems from inside the app, with a screenshot when it helps. Screenshots can show personal data, so the user can redact them before sending and they are encrypted and short-lived once stored. A small set of admin tools keeps this and other stored data under control.

## Requirements

### Requirement: Users can report an issue

A signed-in user SHALL be able to submit a report with a title of at most 200 characters, a description of at most 5000 characters and an optional screenshot of at most 5 MB whose content is a JPEG, PNG, GIF or WebP image. An oversized screenshot SHALL be refused as too large and any other file type as unsupported. Screenshots SHALL be encrypted at rest; if encryption fails the report SHALL be refused rather than stored in the clear. A user SHALL submit at most 5 reports per hour and 20 per 24 hours.

#### Scenario: Disguised file
- GIVEN a PDF renamed to screenshot.png
- WHEN it is attached to a report
- THEN the report is refused as an unsupported type

#### Scenario: Daily cap
- GIVEN a user who submitted 20 reports in the last 24 hours
- WHEN they submit another
- THEN it is refused as rate limited

### Requirement: Screenshots can be redacted before sending

Before submitting, the user SHALL be able to edit the screenshot with redact, highlight, arrow and text tools and undo. Saving SHALL flatten the image and every annotation into a single JPEG, with redactions painted opaquely over the original pixels, and only that flattened image SHALL be submitted. Re-opening the editor SHALL start from the last saved image, so earlier redactions are kept.

#### Scenario: Redacted screenshot
- GIVEN a screenshot with the user's email redacted in the editor
- WHEN the report is submitted
- THEN the stored screenshot shows a black box where the email was
- AND the unredacted original is not sent

#### Scenario: Second edit
- GIVEN a screenshot saved with redaction A
- WHEN the user re-opens the editor, adds redaction B and saves
- THEN the submitted image contains both redactions

### Requirement: Admin tools are restricted

Listing feedback, scrubbing screenshots and purging feedback, duels or swipes SHALL be available only to admin users; anyone else SHALL be refused with "Admin access required". Each admin tool SHALL be rate limited.

#### Scenario: Non-admin
- GIVEN a signed-in user who is not an admin
- WHEN they list feedback reports
- THEN the request is refused with "Admin access required"
