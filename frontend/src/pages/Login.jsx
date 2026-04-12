export default function Login() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen relative overflow-hidden">
      {/* Background gradient overlay */}
      <div className="fixed inset-0 z-0">
        <div className="absolute inset-0 bg-gradient-to-t from-[#0F0E0D] via-transparent to-transparent opacity-80 z-10" />
        <div className="absolute inset-0 bg-[#0F0E0D]" />
      </div>

      {/* Main content */}
      <main className="relative z-20 flex flex-col items-center text-center px-6">
        {/* Logo */}
        <div className="mb-8">
          <img src="/logo.png" alt="FilmDuel" className="w-16 h-16 mx-auto opacity-90" />
        </div>

        {/* Wordmark */}
        <h1 className="font-headline font-black text-6xl md:text-8xl tracking-tighter text-[#E8A020] mb-12">
          FILMDUEL
        </h1>

        {/* CTA Section */}
        <div className="flex flex-col items-center gap-16">
          <a
            href="/auth/login"
            className="group flex items-center gap-4 bg-[#ffbe5b] px-10 py-5 font-headline font-bold text-[#442b00] tracking-widest uppercase transition-all duration-300 hover:scale-105 active:scale-95 shadow-[0_0_40px_rgba(232,160,32,0.2)] text-lg"
          >
            Sign in with Trakt
          </a>

          {/* Muted footer text */}
          <div className="flex flex-col gap-2">
            <p className="font-label text-[#d6c4ae]/40 uppercase tracking-[0.3em] text-[10px] md:text-xs">
              Rate films. Rank everything.
            </p>
            <div className="w-12 h-[1px] bg-[#514534]/20 mx-auto mt-4" />
          </div>
        </div>
      </main>

      {/* Decorative elements */}
      <div className="fixed top-12 left-12 opacity-5 hidden md:block pointer-events-none">
        <span className="font-headline text-9xl font-black select-none">ACT I</span>
      </div>
      <div className="fixed bottom-12 right-12 opacity-5 hidden md:block pointer-events-none">
        <span className="font-headline text-9xl font-black select-none">24FPS</span>
      </div>
    </div>
  );
}
