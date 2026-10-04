import { describe, it, expect, vi, beforeEach } from "vitest";
import * as Sentry from "@sentry/react";
import { initSentry, scrubBreadcrumb, scrubEvent } from "../lib/sentry";

vi.mock("@sentry/react", () => ({
  init: vi.fn(),
  breadcrumbsIntegration: vi.fn((options) => ({ name: "Breadcrumbs", options })),
}));

describe("initSentry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does nothing without a DSN", () => {
    expect(initSentry("")).toBe(false);
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it("initialises with PII off, scrubbing, and no DOM/console breadcrumbs", () => {
    expect(initSentry("https://k@o1.ingest.sentry.io/1")).toBe(true);
    expect(Sentry.init).toHaveBeenCalledTimes(1);
    const options = Sentry.init.mock.calls[0][0];
    expect(options.sendDefaultPii).toBe(false);
    expect(options.beforeSend).toBe(scrubEvent);
    expect(options.beforeBreadcrumb).toBe(scrubBreadcrumb);
    expect(Sentry.breadcrumbsIntegration).toHaveBeenCalledWith({ console: false, dom: false });
  });
});

describe("scrubEvent", () => {
  it("strips the query string, query data and Referer from the request", () => {
    const event = scrubEvent({
      request: {
        url: "https://filmduel.example/auth/callback?code=x&state=y",
        query_string: "code=x&state=y",
        headers: { Referer: "https://filmduel.example/?code=x", "User-Agent": "ua" },
      },
    });
    expect(event.request.url).toBe("https://filmduel.example/auth/callback");
    expect(event.request).not.toHaveProperty("query_string");
    expect(event.request.headers).toEqual({ "User-Agent": "ua" });
  });

  it("leaves events without a request alone", () => {
    expect(scrubEvent({ message: "boom" })).toEqual({ message: "boom" });
  });
});

describe("scrubBreadcrumb", () => {
  it("strips query strings from request and navigation URLs", () => {
    const fetchCrumb = scrubBreadcrumb({
      category: "fetch",
      data: { url: "/api/movies/pair?last_pair_token=secret", method: "GET" },
    });
    expect(fetchCrumb.data).toEqual({ url: "/api/movies/pair", method: "GET" });

    const navCrumb = scrubBreadcrumb({
      category: "navigation",
      data: { from: "/duel?x=1#frag", to: "/auth/callback?code=x" },
    });
    expect(navCrumb.data).toEqual({ from: "/duel", to: "/auth/callback" });
  });
});
