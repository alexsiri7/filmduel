import { useState } from "react";
import { acceptConsent } from "../api";

export default function ConsentModal({ onAccepted }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleAccept = async () => {
    setLoading(true);
    setError(null);
    try {
      await acceptConsent("2.0");
      onAccepted();
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
          <li>• OAuth tokens from Trakt (stored encrypted)</li>
          <li>• Your watched film history from Trakt</li>
          <li>• Duel choices and ELO rankings</li>
          <li>• Film titles, years, genres &amp; preference tiers sent to Requesty.ai for AI recommendations</li>
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
      </div>
    </div>
  );
}
