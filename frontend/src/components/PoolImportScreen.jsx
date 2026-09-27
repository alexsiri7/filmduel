import { useState, useEffect } from "react";
import { getMe, retryPoolImport } from "../api";

const POLL_INTERVAL_MS = 3000;

export default function PoolImportScreen({ initialStatus, onDone }) {
  const [status, setStatus] = useState(initialStatus);
  const [polls, setPolls] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (status === "complete" || status == null) onDone();
  }, [status, onDone]);

  useEffect(() => {
    if (status !== "importing") return undefined;
    const timer = setTimeout(async () => {
      try {
        const me = await getMe();
        setStatus(me.pool_import_status);
      } catch (err) {
        // Only the server decides an import failed; keep polling through blips.
        console.error("Import status check failed:", err);
      }
      setPolls((n) => n + 1);
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [status, polls]);

  const handleRetry = async () => {
    setRetrying(true);
    setError(null);
    try {
      const me = await retryPoolImport();
      setStatus(me.pool_import_status);
    } catch (err) {
      setError(err.message || "Retry failed. Please try again later.");
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#0F0E0D]/95 backdrop-blur-sm flex items-center justify-center px-4">
      <div className="max-w-md w-full bg-[#141312] p-8 border border-[#514534]/30">
        <img src="/logo.png" alt="FilmDuel" className="w-10 h-10 mb-6" />
        {status === "failed" ? (
          <>
            <h2 className="font-headline font-black text-2xl tracking-tighter text-[#E8A020] mb-2 uppercase">
              Import incomplete
            </h2>
            <p className="font-body text-[#d6c4ae] text-sm mb-6">
              We couldn't finish importing your library. Trakt may be slow right now.
            </p>
            {error && <p className="text-[#C04A20] text-sm mb-4">{error}</p>}
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="w-full bg-[#ffbe5b] text-[#442b00] font-headline font-black uppercase py-4 tracking-widest transition-all hover:scale-[1.02] active:scale-95 disabled:opacity-50 mb-3"
            >
              Retry import
            </button>
            <button
              onClick={onDone}
              className="w-full text-[#E8A020]/70 hover:text-[#E8A020] text-xs font-headline uppercase tracking-widest py-2 transition-colors"
            >
              Continue anyway
            </button>
          </>
        ) : (
          <>
            <h2 className="font-headline font-black text-2xl tracking-tighter text-[#E8A020] mb-2 uppercase">
              Importing your library
            </h2>
            <p className="font-body text-[#d6c4ae] text-sm mb-6">
              Fetching your films and shows from Trakt. This usually takes under a minute.
            </p>
            <div className="text-muted-foreground font-headline uppercase tracking-widest animate-pulse">
              Importing...
            </div>
          </>
        )}
      </div>
    </div>
  );
}
