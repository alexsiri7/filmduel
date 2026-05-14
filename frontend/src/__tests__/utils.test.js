import { describe, it, expect } from "vitest";
import { mediaLabel, sanitizePosterUrl } from "../lib/utils";

describe("mediaLabel", () => {
  it('returns "show" for mediaType "show"', () => {
    expect(mediaLabel("show")).toBe("show");
  });

  it('returns "film" for mediaType "movie"', () => {
    expect(mediaLabel("movie")).toBe("film");
  });

  it('returns "film" for unknown/undefined mediaType', () => {
    expect(mediaLabel(undefined)).toBe("film");
    expect(mediaLabel(null)).toBe("film");
    expect(mediaLabel("tv")).toBe("film");
  });
});

describe("sanitizePosterUrl", () => {
  it("accepts valid TMDB https URL", () => {
    const url = "https://image.tmdb.org/t/p/w500/abc123.jpg";
    expect(sanitizePosterUrl(url)).toBe(url);
  });

  it("rejects data: URI", () => {
    expect(sanitizePosterUrl("data:image/png;base64,abc")).toBeNull();
  });

  it("rejects javascript: URI", () => {
    expect(sanitizePosterUrl("javascript:alert(1)")).toBeNull();
  });

  it("rejects http (non-https) TMDB URL", () => {
    expect(sanitizePosterUrl("http://image.tmdb.org/t/p/w500/abc.jpg")).toBeNull();
  });

  it("rejects arbitrary https URL from another origin", () => {
    expect(sanitizePosterUrl("https://evil.example.com/img.jpg")).toBeNull();
  });

  it("rejects TMDB lookalike subdomain", () => {
    expect(sanitizePosterUrl("https://evil.image.tmdb.org/img.jpg")).toBeNull();
  });

  it("returns null for null input", () => {
    expect(sanitizePosterUrl(null)).toBeNull();
  });

  it("returns null for undefined input", () => {
    expect(sanitizePosterUrl(undefined)).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(sanitizePosterUrl("")).toBeNull();
  });

  it("returns null for malformed URL", () => {
    expect(sanitizePosterUrl("not-a-url")).toBeNull();
  });
});
