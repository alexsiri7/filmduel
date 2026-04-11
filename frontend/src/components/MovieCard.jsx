import { Card, CardContent } from "./ui/card";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";

export default function MovieCard({
  movie,
  onClick,
  delta,
  highlight,
  clickable = false,
  compact = false,
}) {
  const posterSrc = movie.poster_url
    ? movie.poster_url
    : "https://via.placeholder.com/300x450?text=No+Poster";

  const genres = (movie.genres || []).slice(0, 2);

  return (
    <Card
      className={cn(
        "w-full overflow-hidden transition-all duration-200",
        compact ? "max-w-[200px]" : "max-w-[280px]",
        clickable &&
          "cursor-pointer hover:scale-[1.03] hover:shadow-xl hover:shadow-primary/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.98]",
        !clickable && "cursor-default",
        highlight && "ring-2 ring-primary shadow-lg shadow-primary/20"
      )}
      onClick={clickable ? onClick : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
    >
      <div className="aspect-[2/3] overflow-hidden bg-secondary relative">
        <img
          className="w-full h-full object-cover"
          src={posterSrc}
          alt={`${movie.title} poster`}
          loading="lazy"
          onError={(e) => {
            e.target.src =
              "https://via.placeholder.com/300x450/1a1a2e/666?text=No+Poster";
          }}
        />
        {clickable && (
          <div className="absolute inset-0 bg-primary/0 hover:bg-primary/10 transition-colors" />
        )}
      </div>
      <CardContent className="p-3 space-y-1.5">
        <h3 className="font-semibold text-sm leading-tight line-clamp-2">
          {movie.title}
        </h3>
        <div className="flex items-center gap-2">
          {movie.year && (
            <span className="text-xs text-muted-foreground">{movie.year}</span>
          )}
          {genres.map((g) => (
            <Badge
              key={g}
              variant="secondary"
              className="text-[10px] px-1.5 py-0"
            >
              {g}
            </Badge>
          ))}
        </div>
        {/* ELO + battles for ranked movies */}
        {movie.elo != null && (
          <div className="flex items-center justify-between pt-0.5">
            <span className="text-xs font-mono font-semibold text-primary">
              {movie.elo} ELO
            </span>
            {movie.battles != null && (
              <span className="text-[10px] text-muted-foreground">
                {movie.battles} battles
              </span>
            )}
          </div>
        )}
        {/* ELO delta after duel */}
        {delta !== undefined && delta !== null && (
          <div className="pt-0.5">
            <span
              className={cn(
                "text-sm font-bold font-mono",
                delta >= 0 ? "text-positive" : "text-negative"
              )}
            >
              {delta >= 0 ? "+" : ""}
              {delta}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
