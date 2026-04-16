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
