import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export function mediaLabel(mediaType) {
  return mediaType === "show" ? "show" : "film";
}

export function mediaLabelCap(mediaType) {
  return mediaType === "show" ? "Show" : "Film";
}

const ALLOWED_POSTER_ORIGIN = "image.tmdb.org";

/**
 * Validates that a poster URL is a safe HTTPS URL from the TMDB CDN.
 * Returns null for any URL that does not originate from image.tmdb.org,
 * preventing data: URIs or unexpected origins from reaching <img src>.
 *
 * @param {string|null|undefined} url
 * @returns {string|null}
 */
export function sanitizePosterUrl(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" && parsed.hostname === ALLOWED_POSTER_ORIGIN) {
      return url;
    }
    return null;
  } catch {
    return null;
  }
}
