const Divider = () => <div className="w-full h-[1px] bg-[#514534]/20 mb-10" />;

export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-[#0F0E0D] text-[#F5F0E8]">
      <div className="max-w-3xl mx-auto px-6 py-16">
        <h1 className="font-headline font-black text-4xl tracking-tighter text-[#E8A020] mb-2">
          PRIVACY POLICY
        </h1>
        <p className="text-[#6B6760] text-sm font-body mb-12">Version 1.0 · May 2026</p>

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            What We Collect
          </h2>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body">
            <li>• <strong className="text-[#F5F0E8]">OAuth tokens</strong> from Trakt (stored encrypted at rest)</li>
            <li>• <strong className="text-[#F5F0E8]">Watch history</strong> imported from your Trakt account</li>
            <li>• <strong className="text-[#F5F0E8]">Duel choices and ELO rankings</strong> generated through your matchup decisions</li>
            <li>• <strong className="text-[#F5F0E8]">Taste profiles</strong> sent to AI services for personalized recommendations</li>
            <li>• <strong className="text-[#F5F0E8]">Error reports</strong> sent to Sentry for application stability</li>
            <li>• <strong className="text-[#F5F0E8]">Session cookies</strong> (strictly necessary, httponly, samesite=lax)</li>
          </ul>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Why We Collect It
          </h2>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed">
            We collect this data to provide FilmDuel's core features: importing your film history,
            generating ELO rankings through head-to-head duels, running bracket tournaments, and
            delivering AI-powered watch recommendations. Without this data, the service cannot function.
          </p>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Third-Party Services
          </h2>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body">
            <li>• <strong className="text-[#F5F0E8]">Trakt</strong> — OAuth authentication and watch history import</li>
            <li>• <strong className="text-[#F5F0E8]">TMDB</strong> — Movie poster images and metadata</li>
            <li>• <strong className="text-[#F5F0E8]">OpenRouter (LLM provider)</strong> — AI-powered recommendations using your taste profile</li>
            <li>• <strong className="text-[#F5F0E8]">Sentry</strong> — Error tracking and application monitoring (no PII sent)</li>
          </ul>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Data Retention
          </h2>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed">
            Your account data is retained until you choose to delete it. You can delete your account
            at any time through the application settings. Deletion is permanent and removes all
            associated data including rankings, duels, and tournament history.
          </p>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Your Rights (GDPR)
          </h2>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed mb-4">
            Under the General Data Protection Regulation, you have the right to:
          </p>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body">
            <li>• <strong className="text-[#F5F0E8]">Access</strong> — Request a copy of the data we hold about you</li>
            <li>• <strong className="text-[#F5F0E8]">Rectification</strong> — Request correction of inaccurate data</li>
            <li>• <strong className="text-[#F5F0E8]">Erasure</strong> — Delete your account and all associated data</li>
            <li>• <strong className="text-[#F5F0E8]">Portability</strong> — Request your data in a portable format</li>
          </ul>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Contact
          </h2>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed">
            For data requests or privacy concerns, please open an issue on our{" "}
            <a
              href="https://github.com/alexsiri7/filmduel/issues"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#E8A020] hover:text-[#E8A020]/80 transition-colors"
            >
              GitHub repository
            </a>
            .
          </p>
        </section>

        <Divider />

        <p className="text-[#6B6760] text-xs font-body">
          Last updated: May 2026
        </p>
      </div>
    </div>
  );
}
