import { Card, CardContent } from "./ui/card";
import { cn } from "../lib/utils";

export default function MovieCard({ movie, onClick, delta, highlight, disabled }) {
  const posterSrc = movie.poster_url
    ? movie.poster_url
    : "https://placehold.co/300x450?text=No+Poster";

  return (
    <Card
      className={cn(
        "w-full max-w-[280px] overflow-hidden cursor-pointer transition-all duration-200 hover:scale-[1.02] hover:shadow-lg hover:shadow-primary/10",
        highlight && "ring-2 ring-primary",
        disabled && "opacity-60 cursor-default pointer-events-none"
      )}
      onClick={disabled ? undefined : onClick}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick();
        }
      }}
      aria-disabled={disabled}
    >
      <div className="aspect-[2/3] overflow-hidden">
        <img
          className="w-full h-full object-cover"
          src={posterSrc}
          alt={`${movie.title} poster`}
          loading="lazy"
        />
      </div>
      <CardContent className="p-4">
        <h3 className="font-semibold text-base leading-tight truncate">
          {movie.title}
        </h3>
        <div className="flex items-center justify-between mt-1">
          {movie.year && (
            <span className="text-sm text-muted-foreground">{movie.year}</span>
          )}
          {delta !== undefined && delta !== null && (
            <span
              className={cn(
                "text-sm font-bold",
                delta >= 0 ? "text-positive" : "text-negative"
              )}
            >
              {delta >= 0 ? "+" : ""}
              {delta}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
