// Frontend error tracking (#648). Mirrors the backend's SEC-15 Sentry scrubbing
// (_scrub_event / _scrub_breadcrumb in backend/main.py): query strings carry OAuth
// code/state and pair tokens, and DOM/console text can contain film titles, which
// are preference data — none of it may reach Sentry.
import * as Sentry from "@sentry/react";

export function stripQuery(url) {
  return url.split(/[?#]/, 1)[0];
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
  return event;
}

export function scrubBreadcrumb(crumb) {
  const data = crumb.data;
  if (data) {
    for (const key of ["url", "from", "to"]) {
      if (typeof data[key] === "string") data[key] = stripQuery(data[key]);
    }
  }
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
