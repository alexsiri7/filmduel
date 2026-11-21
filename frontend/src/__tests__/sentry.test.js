import { describe, it, expect, vi, beforeEach } from "vitest";
import * as Sentry from "@sentry/react";
import { initSentry, redactText, scrubBreadcrumb, scrubEvent } from "../lib/sentry";

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

const USER_ID = "3f2b8c1e-9d4a-4b7e-8c21-5a6f0e9d1b23";

describe("redactText", () => {
  it("cuts embedded URLs at the query, masks /users/<id> and filters UUIDs", () => {
    expect(
      redactText(
        `GET https://api.trakt.tv/users/alice/history?code=x failed for ${USER_ID.toUpperCase()}`,
      ),
    ).toBe("GET https://api.trakt.tv/users/[Filtered]/history failed for [Filtered]");
  });

  it("redacts every URL, user path and UUID in the text, not just the first", () => {
    const otherId = "9c1a2b3d-4e5f-6071-8293-a4b5c6d7e8f9";
    expect(redactText(`${USER_ID} then ${otherId}`)).toBe("[Filtered] then [Filtered]");
    expect(
      redactText("GET https://a.example/users/alice/users/bob?k=1 then https://b.example/y#k=2"),
    ).toBe("GET https://a.example/users/[Filtered]/users/[Filtered] then https://b.example/y");
  });

  it("leaves text without URLs or UUIDs alone", () => {
    expect(redactText("Network error")).toBe("Network error");
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

  it("redacts URLs and UUIDs in the message and exception values", () => {
    const event = scrubEvent({
      message: `no pair for ${USER_ID}`,
      exception: {
        values: [
          { type: "TypeError", value: "Failed to fetch https://filmduel.example/duel?last_pair_token=s" },
          { type: "Error", value: `user ${USER_ID} not found` },
          { type: "Error" },
        ],
      },
    });
    expect(event.message).toBe("no pair for [Filtered]");
    expect(event.exception.values).toEqual([
      { type: "TypeError", value: "Failed to fetch https://filmduel.example/duel" },
      { type: "Error", value: "user [Filtered] not found" },
      { type: "Error" },
    ]);
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

  it("redacts URLs and UUIDs in the message", () => {
    const crumb = scrubBreadcrumb({
      category: "ui",
      message: `opened https://filmduel.example/auth/callback?code=x as ${USER_ID}`,
    });
    expect(crumb.message).toBe("opened https://filmduel.example/auth/callback as [Filtered]");
  });
});
