export default function Login() {
  return (
    <div className="min-h-screen relative overflow-hidden">
      {/* Background */}
      <div className="fixed inset-0 z-0 bg-[#0F0E0D]" />

      {/* Content */}
      <div className="relative z-20">

        {/* ── Hero Section ── */}
        <section className="flex flex-col items-center justify-center min-h-screen text-center px-6">
          {/* Decorative top line */}
          <div className="w-16 h-[2px] bg-[#E8A020]/30 mb-10" />

          <img src="/logo.png" alt="FilmDuel" className="w-16 h-16 mx-auto opacity-90 mb-6" />

          <h1 className="font-headline font-black text-6xl md:text-8xl tracking-tighter text-[#E8A020] mb-4">
            FILMDUEL
          </h1>

          <p className="font-body text-[#d6c4ae] text-lg md:text-xl max-w-md mb-12">
            Rank every film you've ever seen.
          </p>

          <a
            href="/auth/login"
            className="group flex items-center gap-4 bg-[#ffbe5b] px-10 py-5 font-headline font-bold text-[#442b00] tracking-widest uppercase transition-all duration-300 hover:scale-105 active:scale-95 shadow-[0_0_40px_rgba(232,160,32,0.2)] text-lg"
          >
            Sign in with Trakt
          </a>

          {/* Scroll hint */}
          <div className="mt-16 animate-bounce text-[#6B6760]">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="square" strokeLinejoin="miter" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </section>

        {/* ── Divider ── */}
        <div className="flex items-center justify-center gap-4 py-2">
          <div className="w-24 h-[1px] bg-[#514534]/40" />
          <span className="font-label text-[#6B6760] uppercase tracking-[0.3em] text-[10px]">How It Works</span>
          <div className="w-24 h-[1px] bg-[#514534]/40" />
        </div>

        {/* ── How It Works ── */}
        <section className="max-w-4xl mx-auto px-6 py-24">
          <div className="grid md:grid-cols-3 gap-8">
            {/* Step 1 */}
            <div className="bg-[#1d1b1a] border border-[#514534]/20 p-8 flex flex-col items-center text-center">
              <span className="font-headline font-black text-5xl text-[#E8A020]/20 mb-4">01</span>
              <h3 className="font-headline font-bold text-[#F5F0E8] uppercase tracking-wider text-sm mb-3">Import</h3>
              <p className="font-body text-[#d6c4ae] text-sm leading-relaxed">
                Connect your Trakt account to import your watched films. Your history becomes your catalog.
              </p>
            </div>

            {/* Step 2 */}
            <div className="bg-[#1d1b1a] border border-[#514534]/20 p-8 flex flex-col items-center text-center">
              <span className="font-headline font-black text-5xl text-[#E8A020]/20 mb-4">02</span>
              <h3 className="font-headline font-bold text-[#F5F0E8] uppercase tracking-wider text-sm mb-3">Swipe</h3>
              <p className="font-body text-[#d6c4ae] text-sm leading-relaxed">
                Classify films as seen or unseen in quick swipe sessions. Build your personal library fast.
              </p>
            </div>

            {/* Step 3 */}
            <div className="bg-[#1d1b1a] border border-[#514534]/20 p-8 flex flex-col items-center text-center">
              <span className="font-headline font-black text-5xl text-[#E8A020]/20 mb-4">03</span>
              <h3 className="font-headline font-bold text-[#F5F0E8] uppercase tracking-wider text-sm mb-3">Duel</h3>
              <p className="font-body text-[#d6c4ae] text-sm leading-relaxed">
                Pick winners in head-to-head matchups to build your ELO ranking. Every duel sharpens your list.
              </p>
            </div>
          </div>
        </section>

        {/* ── Divider ── */}
        <div className="flex items-center justify-center gap-4 py-2">
          <div className="w-24 h-[1px] bg-[#514534]/40" />
          <span className="font-label text-[#6B6760] uppercase tracking-[0.3em] text-[10px]">Features</span>
          <div className="w-24 h-[1px] bg-[#514534]/40" />
        </div>

        {/* ── Features Highlight ── */}
        <section className="max-w-3xl mx-auto px-6 py-24">
          <div className="flex flex-col gap-8">
            <div className="flex items-start gap-6">
              <span className="font-headline font-black text-[#E8A020] text-lg shrink-0">&#9670;</span>
              <div>
                <h4 className="font-headline font-bold text-[#F5F0E8] uppercase tracking-wider text-sm mb-1">Tournaments</h4>
                <p className="font-body text-[#d6c4ae] text-sm">
                  Run bracket-style tournaments across genres, decades, or directors. Crown your ultimate champion.
                </p>
              </div>
            </div>

            <div className="w-full h-[1px] bg-[#514534]/20" />

            <div className="flex items-start gap-6">
              <span className="font-headline font-black text-[#E8A020] text-lg shrink-0">&#9670;</span>
              <div>
                <h4 className="font-headline font-bold text-[#F5F0E8] uppercase tracking-wider text-sm mb-1">Rankings Export</h4>
                <p className="font-body text-[#d6c4ae] text-sm">
                  Export your personal rankings and share your definitive film list with the world.
                </p>
              </div>
            </div>

            <div className="w-full h-[1px] bg-[#514534]/20" />

            <div className="flex items-start gap-6">
              <span className="font-headline font-black text-[#E8A020] text-lg shrink-0">&#9670;</span>
              <div>
                <h4 className="font-headline font-bold text-[#F5F0E8] uppercase tracking-wider text-sm mb-1">Smart Matchmaking</h4>
                <p className="font-body text-[#d6c4ae] text-sm">
                  Intelligent pairing finds the matchups that matter most, so every duel counts.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Bottom CTA ── */}
        <section className="flex flex-col items-center text-center px-6 pb-24 pt-8">
          <div className="w-16 h-[2px] bg-[#E8A020]/30 mb-10" />

          <p className="font-label text-[#d6c4ae]/40 uppercase tracking-[0.3em] text-[10px] md:text-xs mb-8">
            Rate films. Rank everything.
          </p>

          <a
            href="/auth/login"
            className="group flex items-center gap-4 bg-[#ffbe5b] px-10 py-5 font-headline font-bold text-[#442b00] tracking-widest uppercase transition-all duration-300 hover:scale-105 active:scale-95 shadow-[0_0_40px_rgba(232,160,32,0.2)] text-lg"
          >
            Sign in with Trakt
          </a>

          <div className="w-12 h-[1px] bg-[#514534]/20 mx-auto mt-16" />
          <p className="font-label text-[#6B6760] text-[10px] mt-4 uppercase tracking-widest">
            FilmDuel &mdash; A Noir Projectionist Experience
          </p>
        </section>

      </div>

      {/* Decorative background elements */}
      <div className="fixed top-12 left-12 opacity-5 hidden md:block pointer-events-none">
        <span className="font-headline text-9xl font-black select-none">ACT I</span>
      </div>
      <div className="fixed bottom-12 right-12 opacity-5 hidden md:block pointer-events-none">
        <span className="font-headline text-9xl font-black select-none">24FPS</span>
      </div>
    </div>
  );
}
