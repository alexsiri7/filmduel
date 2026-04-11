export default function MovieCard({ movie, onClick, delta }) {
  const posterSrc = movie.poster_url
    ? movie.poster_url
    : "https://via.placeholder.com/300x450?text=No+Poster";

  return (
    <div className="movie-card" onClick={onClick} role="button" tabIndex={0}>
      <img
        className="movie-poster"
        src={posterSrc}
        alt={`${movie.title} poster`}
        loading="lazy"
      />
      <div className="movie-info">
        <h3>{movie.title}</h3>
        {movie.year && <span className="movie-year">{movie.year}</span>}
        {delta !== undefined && delta !== null && (
          <span className={`elo-delta ${delta >= 0 ? "positive" : "negative"}`}>
            {delta >= 0 ? "+" : ""}
            {delta}
          </span>
        )}
      </div>
    </div>
  );
}
