import { useState } from "react";
import { acceptConsent } from "../api";
import { DeleteAccountControl, DownloadDataLink } from "./AccountActions";
import { CURRENT_PRIVACY_POLICY_VERSION } from "../constants";

export default function ConsentModal({ onAccepted }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleAccept = async () => {
    setLoading(true);
    setError(null);
    try {
      const user = await acceptConsent(CURRENT_PRIVACY_POLICY_VERSION);
      onAccepted(user);
    } catch (err) {
      console.error("Failed to record consent:", err);
      setError(err.message || "Failed to save. Please try again.");
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#0F0E0D]/95 backdrop-blur-sm flex items-center justify-center px-4">
      <div className="max-w-md w-full bg-[#141312] p-8 border border-[#514534]/30">
        <img src="/logo.png" alt="FilmDuel" className="w-10 h-10 mb-6" />
        <h2 className="font-headline font-black text-2xl tracking-tighter text-[#E8A020] mb-2 uppercase">
          Before you continue
        </h2>
        <p className="font-body text-[#d6c4ae] text-sm mb-6">
          FilmDuel collects the following data to provide its service:
        </p>
        <ul className="space-y-2 mb-6 text-[#d6c4ae] text-sm font-body">
          <li>• Your account details and OAuth tokens from the service you sign in with, Trakt or SIMKL (tokens stored encrypted)</li>
          <li>• Your watch history and ratings from Trakt or SIMKL</li>
          <li>• Duel choices and ELO rankings</li>
          <li>• <strong>AI Watch Suggestions</strong> — your top 10 and bottom 5 ranked films (title, year, genres, preference tier), per-genre affinities, total ranked count, and a candidate pool of up to 50 films from the catalog (title, year, genres, community rating) are sent to Requesty.ai</li>
          <li>• <strong>AI-Curated Tournaments</strong> — candidate films (title, year, genres, preference tier, duel count) plus any theme or filter you enter are sent to Requesty.ai</li>
          <li>• Raw ELO scores and account identifiers are never transmitted</li>
          <li>• Feedback reports you choose to send, including any screenshot you attach (stored encrypted)</li>
          <li>• Hosting and storage: the app runs on Railway, which logs your IP address; your data is stored in Supabase; rate-limit counters keyed by IP address are kept in Redis</li>
          <li>• Poster images load directly from TMDB, which receives your IP address and which posters you view</li>
          <li>• Error reports sent to Sentry</li>
        </ul>
        <a
          href="/privacy"
          target="_blank"
          rel="noopener noreferrer"
          className="block text-[#E8A020]/70 hover:text-[#E8A020] text-xs font-headline uppercase tracking-widest mb-8 transition-colors"
        >
          Read full Privacy Policy →
        </a>
        {error && <p className="text-[#C04A20] text-sm mb-4">{error}</p>}
        <button
          onClick={handleAccept}
          disabled={loading}
          className="w-full bg-[#ffbe5b] text-[#442b00] font-headline font-black uppercase py-4 tracking-widest transition-all hover:scale-[1.02] active:scale-95 disabled:opacity-50"
        >
          {loading ? "Saving..." : "I Accept"}
        </button>
        <div className="mt-6 pt-4 border-t border-[#514534]/30">
          <p className="text-[#6B6760] text-xs font-body mb-2">
            Without consent you can still take your data out or erase it.
          </p>
          <DownloadDataLink />
          <DeleteAccountControl />
        </div>
      </div>
    </div>
  );
}
