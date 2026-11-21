// Frontend error tracking (#648). Mirrors the backend's SEC-15 Sentry scrubbing
// (_scrub_event / _scrub_breadcrumb in backend/observability.py): query strings
// carry OAuth code/state and pair tokens, user ids are UUIDs, and DOM/console
// text can contain film titles, which are preference data — none of it may reach
// Sentry.
import * as Sentry from "@sentry/react";

const PROVIDER_USER_PATH = /\/users\/[^/?#\s]+/g;
const URL_IN_TEXT = /https?:\/\/[^\s'"<>]+/g;
const UUID_IN_TEXT = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;

export function stripQuery(url) {
  return url.split(/[?#]/, 1)[0];
}

// Sentry keeps events after the account is deleted, so no user id may reach it
// through error text, such as a failed fetch's message.
export function redactText(text) {
  return text
    .replace(URL_IN_TEXT, (url) => stripQuery(url).replace(PROVIDER_USER_PATH, "/users/[Filtered]"))
    .replace(UUID_IN_TEXT, "[Filtered]");
}

export function scrubEvent(event) {
  const request = event.request;
  if (request) {
    if (typeof request.url === "string") request.url = stripQuery(request.url);
    delete request.query_string;
    if (request.headers) {
      delete request.headers.Referer;
      delete request.headers.referer;
    }
  }
  if (typeof event.message === "string") event.message = redactText(event.message);
  for (const exc of event.exception?.values ?? []) {
    if (typeof exc.value === "string") exc.value = redactText(exc.value);
  }
  return event;
}

export function scrubBreadcrumb(crumb) {
  const data = crumb.data;
  if (data) {
    for (const key of ["url", "from", "to"]) {
      if (typeof data[key] === "string") data[key] = stripQuery(data[key]);
    }
  }
  if (typeof crumb.message === "string") crumb.message = redactText(crumb.message);
  return crumb;
}

export function initSentry(dsn = import.meta.env.VITE_SENTRY_DSN) {
  if (!dsn) return false;
  Sentry.init({
    dsn,
    sendDefaultPii: false,
    integrations: [Sentry.breadcrumbsIntegration({ console: false, dom: false })],
    beforeSend: scrubEvent,
    beforeBreadcrumb: scrubBreadcrumb,
  });
  return true;
}
