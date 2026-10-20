import { CURRENT_PRIVACY_POLICY_VERSION } from "../constants";

const Divider = () => <div className="w-full h-[1px] bg-[#514534]/20 mb-10" />;

export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-[#0F0E0D] text-[#F5F0E8]">
      <div className="max-w-3xl mx-auto px-6 py-16">
        <h1 className="font-headline font-black text-4xl tracking-tighter text-[#E8A020] mb-2">
          PRIVACY POLICY
        </h1>
        <p className="text-[#6B6760] text-sm font-body mb-12">
          Version {CURRENT_PRIVACY_POLICY_VERSION} · October 2026
        </p>

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            What We Collect
          </h2>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body">
            <li>• <strong className="text-[#F5F0E8]">Account details</strong> from the service you sign in with (Trakt or SIMKL): your user ID and username</li>
            <li>• <strong className="text-[#F5F0E8]">OAuth tokens</strong> from Trakt or SIMKL (stored encrypted at rest)</li>
            <li>• <strong className="text-[#F5F0E8]">Watch history and ratings</strong> imported from your Trakt or SIMKL account</li>
            <li>• <strong className="text-[#F5F0E8]">Duel choices and ELO rankings</strong> generated through your matchup decisions, plus your swipe answers, tournaments and responses to Watch Suggestions</li>
            <li>• <strong className="text-[#F5F0E8]">Taste profiles</strong> — film titles, years, genres, and preference tiers (top/bottom ranked films, genre affinities) — sent to AI providers for personalized recommendations</li>
            <li>• <strong className="text-[#F5F0E8]">Feedback reports</strong> you choose to send: a title, a description and, if you attach one, a screenshot (stored encrypted at rest)</li>
            <li>• <strong className="text-[#F5F0E8]">IP address</strong> — used to rate-limit requests made before you sign in. The rate-limit counters are kept in Redis (see Third-Party Services), or in the application's memory if Redis is unavailable; they expire when the limit's time window ends — at most one day — and are never written to our main database. Your IP address is also recorded in our hosting provider's request logs</li>
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
            <li>• <strong className="text-[#F5F0E8]">Trakt</strong> — OAuth authentication and watch history import; optional write-back of ratings and watchlist entries (see "Changes We Make to Your Trakt or SIMKL Account")</li>
            <li>• <strong className="text-[#F5F0E8]">SIMKL</strong> — OAuth authentication and watch history and ratings import, if you sign in with SIMKL; optional write-back of ratings (see "Changes We Make to Your Trakt or SIMKL Account")</li>
            <li>• <strong className="text-[#F5F0E8]">Railway</strong> — Hosts the FilmDuel application. Every request passes through Railway, which keeps request logs including your IP address</li>
            <li>• <strong className="text-[#F5F0E8]">Supabase</strong> — Hosts the FilmDuel database, where all the data listed above is stored</li>
            <li>• <strong className="text-[#F5F0E8]">Redis</strong> — Holds the rate-limit counters, keyed by your IP address for requests made before you sign in, until each counter's time window ends (at most one day)</li>
            <li>• <strong className="text-[#F5F0E8]">TMDB</strong> — Movie metadata and poster images. Your browser loads poster images directly from TMDB's image server (image.tmdb.org), so TMDB receives your IP address, your browser's user agent and which posters you view — from which it could infer the films in your duels, rankings and suggestions — along with FilmDuel's site address (not the page you are on)</li>
            <li>• <strong className="text-[#F5F0E8]">Requesty.ai (LLM gateway)</strong> — Routes AI requests to underlying models (e.g. Google Gemini). Prompts are not stored by Requesty.ai. EU-hosted (Frankfurt). GDPR DPA available on request.</li>
            <li>• <strong className="text-[#F5F0E8]">Sentry</strong> — Error tracking and application monitoring. Error reports and performance traces are scrubbed before sending: they exclude request bodies (such as feedback text), sign-in codes and other query strings, cookies, and account names and IDs, but may include the API path requested and your browser's user agent.</li>
          </ul>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Changes We Make to Your Trakt or SIMKL Account
          </h2>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body">
            <li>• <strong className="text-[#F5F0E8]">Ratings</strong> — only if you turn on rating sync for that service in settings ("Sync to Trakt" or "Sync to SIMKL"), FilmDuel writes a 1–10 rating, derived from each film's position in your rankings, to that account after duels. Each is off unless you turn it on.</li>
            <li>• <strong className="text-[#F5F0E8]">Watchlist</strong> — when you add a Watch Suggestion to your watchlist, FilmDuel adds that film to your Trakt watchlist (Trakt accounts only).</li>
          </ul>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed mt-4">
            Apart from the ratings you choose to sync, FilmDuel does not write anything to SIMKL.
          </p>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Who Can See Your Data
          </h2>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed">
            Other users cannot see your data. The FilmDuel administrator can read feedback reports,
            including attached screenshots, to investigate the problems they describe, and has access
            to the database to operate and repair the service. The hosting providers above process the
            data only to run the service.
          </p>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            AI Data Sharing
          </h2>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed mb-4">
            When you use AI-powered features (Watch Suggestions, AI-Curated Tournaments),
            the following data is sent to Requesty.ai for processing:
          </p>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed mb-3">
            <strong className="text-[#F5F0E8]">Watch Suggestions</strong> sends:
          </p>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body mb-4">
            <li>• <strong className="text-[#F5F0E8]">Top 10 and bottom 5 ranked films</strong> — title, release year, genres, and a preference tier (e.g. "highly preferred", "neutral")</li>
            <li>• <strong className="text-[#F5F0E8]">Genre affinities</strong> — per-genre preference tier derived from your duel history</li>
            <li>• <strong className="text-[#F5F0E8]">Total number of ranked films</strong></li>
            <li>• <strong className="text-[#F5F0E8]">Candidate film pool</strong> — up to 50 catalog films (title, year, genres, community rating) for the AI to select recommendations from</li>
          </ul>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed mb-3">
            <strong className="text-[#F5F0E8]">AI-Curated Tournaments</strong> sends:
          </p>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body mb-4">
            <li>• <strong className="text-[#F5F0E8]">Candidate films</strong> — title, year, genres, preference tier, and duel count per film</li>
            <li>• <strong className="text-[#F5F0E8]">Filter context and theme hint</strong> — any genre filter or theme text you enter when creating a tournament</li>
          </ul>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed mb-4">
            Raw ELO scores are never transmitted — only bucketed preference tiers.
            No account identifiers (username, user ID, email) are included in AI requests.
          </p>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed">
            <strong className="text-[#F5F0E8]">Opt-out:</strong> Turn off "AI Suggestions" in
            the settings panel of the desktop navigation at any time. While it is off, nothing is
            sent to Requesty.ai: Watch Suggestions and AI-Curated Tournaments are unavailable, and
            every other FilmDuel feature keeps working. You can turn it back on whenever you like.
            Withdrawing your consent to this policy — by deleting your account or contacting us via
            GitHub — also stops all AI processing.
          </p>
        </section>

        <Divider />

        <section className="mb-10">
          <h2 className="font-headline font-bold text-lg text-[#F5F0E8] uppercase tracking-wider mb-4">
            Data Retention
          </h2>
          <ul className="space-y-2 text-[#d6c4ae] text-sm font-body mb-4">
            <li>• <strong className="text-[#F5F0E8]">Duel choices</strong> — the full record of each duel, including the ELO ratings at the time, is kept for 180 days. After that it is deleted and only a minimal duel history entry remains: which film won and which lost (or that you hadn't seen one or both films), and the date. This duel history is kept until you delete your account, so your rankings can be recalculated.</li>
            <li>• <strong className="text-[#F5F0E8]">Swipe answers and Watch Suggestions</strong> — deleted after 180 days</li>
            <li>• <strong className="text-[#F5F0E8]">AI tournament responses</strong> — the AI response stored with a tournament is removed after 180 days; the tournament itself is kept</li>
            <li>• <strong className="text-[#F5F0E8]">Feedback reports</strong> — deleted after 365 days; attached screenshots are deleted after 90 days</li>
            <li>• <strong className="text-[#F5F0E8]">Error reports</strong> — kept by Sentry for the retention period of its plan, not by FilmDuel, and not removed when you delete your account</li>
            <li>• <strong className="text-[#F5F0E8]">Everything else</strong> — your account, rankings, tournaments, and duel history are kept until you delete your account</li>
          </ul>
          <p className="text-[#d6c4ae] text-sm font-body leading-relaxed">
            You can delete your account at any time through the application settings. Deletion is
            permanent and removes all associated data, including rankings, duels, duel history, and
            tournament history. Error reports already sent to Sentry are not part of deletion.
            AI requests processed via Requesty.ai are not stored by Requesty.ai; prompt content is discarded after delivery.
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
            <li>• <strong className="text-[#F5F0E8]">Access</strong> — Download a copy of all the data we hold about you using "Download My Data" in the desktop navigation, or by visiting /api/me/export while signed in</li>
            <li>• <strong className="text-[#F5F0E8]">Rectification</strong> — Request correction of inaccurate data</li>
            <li>• <strong className="text-[#F5F0E8]">Erasure</strong> — Delete your account and all associated data</li>
            <li>• <strong className="text-[#F5F0E8]">Portability</strong> — The same download is a machine-readable JSON file you can take to another service</li>
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
          Last updated: October 2026
        </p>
      </div>
    </div>
  );
}
