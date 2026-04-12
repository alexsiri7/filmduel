import { useState, useRef, useCallback } from "react";

const THRESHOLD = 80;

export default function SwipeCard({ movie, onSwipe }) {
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [exiting, setExiting] = useState(null); // "left" | "right" | null
  const startX = useRef(0);
  const isDragging = useRef(false);

  const posterSrc = movie.poster_url || "https://via.placeholder.com/300x450?text=No+Poster";
  const genres = (movie.genres || []).slice(0, 3);

  const rotation = offset * 0.08;
  const opacity = Math.min(Math.abs(offset) / THRESHOLD, 1);

  const handleStart = useCallback((clientX) => {
    startX.current = clientX;
    isDragging.current = true;
    setDragging(true);
  }, []);

  const handleMove = useCallback((clientX) => {
    if (!isDragging.current) return;
    setOffset(clientX - startX.current);
  }, []);

  const handleEnd = useCallback(() => {
    if (!isDragging.current) return;
    isDragging.current = false;
    setDragging(false);

    if (Math.abs(offset) >= THRESHOLD) {
      const direction = offset > 0 ? "right" : "left";
      setExiting(direction);
      setTimeout(() => {
        onSwipe(direction === "right"); // right = seen, left = unseen
      }, 300);
    } else {
      setOffset(0);
    }
  }, [offset, onSwipe]);

  // Mouse events
  const onMouseDown = (e) => { e.preventDefault(); handleStart(e.clientX); };
  const onMouseMove = (e) => handleMove(e.clientX);
  const onMouseUp = () => handleEnd();

  // Touch events
  const onTouchStart = (e) => handleStart(e.touches[0].clientX);
  const onTouchMove = (e) => handleMove(e.touches[0].clientX);
  const onTouchEnd = () => handleEnd();

  const exitTransform = exiting === "right"
    ? "translateX(120vw) rotate(20deg)"
    : exiting === "left"
    ? "translateX(-120vw) rotate(-20deg)"
    : `translateX(${offset}px) rotate(${rotation}deg)`;

  return (
    <div
      className="relative w-full max-w-[380px] mx-auto select-none touch-none"
      style={{
        transform: exitTransform,
        transition: dragging ? "none" : "transform 0.3s ease-out",
      }}
      onMouseDown={onMouseDown}
      onMouseMove={dragging ? onMouseMove : undefined}
      onMouseUp={onMouseUp}
      onMouseLeave={dragging ? onMouseUp : undefined}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {/* Swipe labels */}
      <div
        className="absolute top-8 right-8 z-20 border-4 border-green-500 rounded-lg px-4 py-2 rotate-12 pointer-events-none"
        style={{ opacity: offset > 0 ? opacity : 0 }}
      >
        <span className="text-green-500 font-headline font-black text-2xl uppercase tracking-wider">
          SEEN
        </span>
      </div>
      <div
        className="absolute top-8 left-8 z-20 border-4 border-red-500 rounded-lg px-4 py-2 -rotate-12 pointer-events-none"
        style={{ opacity: offset < 0 ? opacity : 0 }}
      >
        <span className="text-red-500 font-headline font-black text-2xl uppercase tracking-wider">
          NOPE
        </span>
      </div>

      {/* Card */}
      <div className="aspect-[2/3] overflow-hidden bg-[#1d1b1a] relative rounded-lg shadow-2xl">
        <img
          className="w-full h-full object-cover"
          src={posterSrc}
          alt={`${movie.title} poster`}
          loading="eager"
          draggable={false}
          onError={(e) => {
            e.target.src = "https://via.placeholder.com/300x450/1a1a2e/666?text=No+Poster";
          }}
        />

        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent" />

        {/* Community rating badge */}
        {movie.community_rating && (
          <div className="absolute top-4 right-4 bg-[#E8A020] text-[#0F0E0D] font-headline font-black text-sm px-3 py-1">
            {movie.community_rating.toFixed(0)}
          </div>
        )}

        {/* Bottom overlay: title, year, genres */}
        <div className="absolute bottom-0 left-0 right-0 p-6">
          {genres.length > 0 && (
            <div className="flex gap-2 mb-3">
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
          {movie.year && (
            <p className="text-xs font-label uppercase tracking-[0.3em] text-[#d6c4ae]/80 mb-1">
              {movie.year}
            </p>
          )}
          <h2 className="text-3xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] leading-none">
            {movie.title}
          </h2>
        </div>
      </div>
    </div>
  );
}
