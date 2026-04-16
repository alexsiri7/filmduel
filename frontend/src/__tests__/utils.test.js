import { describe, it, expect } from "vitest";
import { mediaLabel } from "../lib/utils";

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
