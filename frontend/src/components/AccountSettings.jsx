import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { logout, getMe, updateSettings } from "../api";
import { DeleteAccountControl, DownloadDataLink, WithdrawConsentControl } from "./AccountActions";
import ReportIssueModal from "./ReportIssueModal";

function ToggleRow({ label, checked, onToggle }) {
  return (
    <div className="flex items-center justify-between w-full py-2 group">
      <span className="text-[#F5F0E8]/30 group-hover:text-[#F5F0E8]/60 font-headline font-bold uppercase text-xs tracking-widest transition-colors cursor-default">
        {label}
      </span>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={onToggle}
        className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
          checked ? "bg-primary-container" : "bg-[#F5F0E8]/20"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 bg-[#0F0E0D] rounded-full transition-transform ${
            checked ? "translate-x-4" : ""
          }`}
        />
      </button>
    </div>
  );
}

// Rendered in the desktop sidebar and on /settings, so privacy rights are
// reachable on every viewport (GDPR Art. 7(3), PRIV-001).
export default function AccountSettings() {
  const [showFeedback, setShowFeedback] = useState(false);
  const [syncRatings, setSyncRatings] = useState(false);
  const [syncRatingsSimkl, setSyncRatingsSimkl] = useState(false);
  const [hasTrakt, setHasTrakt] = useState(false);
  const [hasSimkl, setHasSimkl] = useState(false);
  const [useAiFeatures, setUseAiFeatures] = useState(true);

  useEffect(() => {
    getMe()
      .then((user) => {
        if (user) {
          setSyncRatings(user.sync_ratings_to_trakt);
          setSyncRatingsSimkl(user.sync_ratings_to_simkl ?? false);
          setUseAiFeatures(user.use_ai_features ?? true);
          setHasTrakt(!!user.trakt_username);
          setHasSimkl(!!user.simkl_username);
        }
      })
      .catch(() => {
        // Leave defaults (safe).
      });
  }, []);

  function makeToggleHandler(currentValue, setter, settingKey, onError) {
    return async () => {
      const next = !currentValue;
      setter(next);
      try {
        await updateSettings({ [settingKey]: next });
      } catch (err) {
        setter(!next); // rollback on failure
        if (onError) onError(err);
      }
    };
  }

  const handleSyncToggle = makeToggleHandler(syncRatings, setSyncRatings, "sync_ratings_to_trakt");
  const handleSimklSyncToggle = makeToggleHandler(syncRatingsSimkl, setSyncRatingsSimkl, "sync_ratings_to_simkl");
  const handleAiToggle = makeToggleHandler(
    useAiFeatures,
    setUseAiFeatures,
    "use_ai_features",
    (err) => console.error("Failed to update AI features setting:", err),
  );

  const handleLogout = async () => {
    await logout();
    window.location.href = "/login";
  };

  return (
    <div className="space-y-3">
      <button
        onClick={() => setShowFeedback(true)}
        className="block w-full text-center text-[#F5F0E8]/30 hover:text-primary-container/70 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
      >
        Report Issue
      </button>
      <Link
        to="/privacy"
        className="block w-full text-center text-[#F5F0E8]/30 hover:text-primary-container/70 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
      >
        Privacy Policy
      </Link>
      <DownloadDataLink />
      <WithdrawConsentControl />
      <DeleteAccountControl />
      {hasTrakt && (
        <ToggleRow label="Sync to Trakt" checked={syncRatings} onToggle={handleSyncToggle} />
      )}
      {hasSimkl && (
        <ToggleRow label="Sync to SIMKL" checked={syncRatingsSimkl} onToggle={handleSimklSyncToggle} />
      )}
      <ToggleRow label="AI Suggestions" checked={useAiFeatures} onToggle={handleAiToggle} />
      <button
        onClick={handleLogout}
        className="w-full text-[#F5F0E8]/30 hover:text-[#F5F0E8]/60 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
      >
        Sign Out
      </button>
      {showFeedback && <ReportIssueModal onClose={() => setShowFeedback(false)} />}
    </div>
  );
}
