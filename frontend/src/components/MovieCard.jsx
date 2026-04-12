import { cn } from "../lib/utils";

export default function MovieCard({
  movie,
  onClick,
  delta,
  highlight,
  clickable = false,
  compact = false,
  chosen, // "winner" | "loser" | undefined
}) {
  const posterSrc = movie.poster_url
    ? movie.poster_url
    : "https://via.placeholder.com/300x450?text=No+Poster";

  const genres = (movie.genres || []).slice(0, 2);

  return (
    <div
      className={cn(
        "relative w-full overflow-hidden transition-all duration-500 group",
        compact ? "max-w-[200px]" : "max-w-[340px]",
        clickable &&
          "cursor-pointer hover:scale-[1.02] active:scale-95",
        !clickable && "cursor-default",
        highlight &&
          "border-2 border-[#E8A020] shadow-[0_0_30px_rgba(232,160,32,0.15)]",
        chosen === "winner" &&
          "border-2 border-[#E8A020] shadow-[0_0_40px_rgba(232,160,32,0.35)] scale-[1.03] animate-winner-pulse",
        chosen === "loser" && "opacity-40 scale-[0.97]"
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
      {/* Poster image */}
      <div className="aspect-[2/3] overflow-hidden bg-[#1d1b1a] relative">
        <img
          className={cn(
            "w-full h-full object-cover transition-all duration-700",
            clickable && "group-hover:scale-110"
          )}
          src={posterSrc}
          alt={`${movie.title} poster`}
          loading="lazy"
          onError={(e) => {
            e.target.src =
              "https://via.placeholder.com/300x450/1a1a2e/666?text=No+Poster";
          }}
        />
        {/* Noir gradient overlay */}
        <div className="absolute inset-0 noir-gradient" />

        {/* Pick winner label when highlighted */}
        {highlight && (
          <div className="absolute -top-0 left-1/2 -translate-x-1/2 z-20">
            <span className="bg-[#E8A020] text-[#442b00] px-4 py-1 font-headline font-bold text-[10px] uppercase tracking-tighter">
              Pick winner
            </span>
          </div>
        )}

        {/* Winner label after duel */}
        {chosen === "winner" && (
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20">
            <span className="bg-[#E8A020] text-[#442b00] px-5 py-2 font-headline font-black text-lg uppercase tracking-wider shadow-[0_0_30px_rgba(232,160,32,0.5)]">
              Winner
            </span>
          </div>
        )}

        {/* Genre badges */}
        {genres.length > 0 && (
          <div className="absolute top-6 left-6 flex gap-2">
            {genres.map((g) => (
              <span
                key={g}
                className="bg-[#0F0E0D]/80 backdrop-blur-md px-3 py-1 text-[10px] font-label font-bold uppercase tracking-widest border border-[#E8A020]/20 text-[#E8A020]"
              >
                {g}
              </span>
            ))}
          </div>
        )}

        {/* Overlay title content */}
        <div className={cn("absolute left-4 right-4", compact ? "bottom-3" : "bottom-6 left-6 right-6")}>
          {movie.year && (
            <p className={cn("font-label uppercase text-[#d6c4ae]/80", compact ? "text-[9px] tracking-[0.2em] mb-1" : "text-xs tracking-[0.3em] mb-2")}>
              {movie.year}
            </p>
          )}
          <h2 className={cn("font-headline font-black uppercase tracking-tighter text-[#F5F0E8] leading-none", compact ? "text-base" : "text-2xl md:text-3xl")}>
            {movie.title}
          </h2>
        </div>
      </div>

      {/* ELO delta after duel */}
      {delta !== undefined && delta !== null && (
        <div className="absolute top-4 right-4 z-10">
          <span
            className={cn(
              "text-lg font-black font-headline px-3 py-1",
              delta >= 0
                ? "bg-[#E8A020] text-[#442b00]"
                : "bg-[#C04A20] text-[#F5F0E8]"
            )}
          >
            {delta >= 0 ? "+" : ""}
            {delta}
          </span>
        </div>
      )}
    </div>
  );
}
