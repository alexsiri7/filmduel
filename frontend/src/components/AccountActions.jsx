import { useState } from "react";
import { deleteAccount, withdrawConsent } from "../api";

const mutedButton =
  "block w-full text-center text-[#F5F0E8]/30 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors";

// A settings action that only runs after an explicit second click. onConfirm is
// expected to navigate away on success; on failure the control resets.
function ConfirmAction({ label, dialogLabel, warning, confirmLabel, pendingLabel, onConfirm }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);

  const handleConfirm = async () => {
    setPending(true);
    try {
      await onConfirm();
    } catch {
      setPending(false);
      setConfirming(false);
    }
  };

  if (!confirming) {
    return (
      <button onClick={() => setConfirming(true)} className={`${mutedButton} hover:text-red-400/80`}>
        {label}
      </button>
    );
  }

  return (
    <div role="alertdialog" aria-label={dialogLabel} className="space-y-2 px-1">
      <p className="text-[#F5F0E8]/60 text-xs font-body">{warning}</p>
      <button
        onClick={handleConfirm}
        disabled={pending}
        className="block w-full text-center bg-red-900/60 text-[#F5F0E8] font-headline font-bold uppercase text-xs tracking-widest py-2 disabled:opacity-50"
      >
        {pending ? pendingLabel : confirmLabel}
      </button>
      <button
        onClick={() => setConfirming(false)}
        disabled={pending}
        className={`${mutedButton} hover:text-[#F5F0E8]/60`}
      >
        Cancel
      </button>
    </div>
  );
}

// Access and erasure do not depend on consent, so these controls are shown both
// in the settings panel and on the consent screen.

export function DownloadDataLink() {
  return (
    <a
      href="/api/me/export"
      download
      className="block w-full text-center text-[#F5F0E8]/30 hover:text-primary-container/70 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
    >
      Download My Data
    </a>
  );
}

export function DeleteAccountControl() {
  return (
    <ConfirmAction
      label="Delete My Account"
      dialogLabel="Confirm account deletion"
      warning="This permanently deletes your account, rankings, tournaments and history. It cannot be undone."
      confirmLabel="Yes, delete everything"
      pendingLabel="Deleting…"
      onConfirm={async () => {
        await deleteAccount();
        window.location.href = "/login";
      }}
    />
  );
}

export function WithdrawConsentControl() {
  return (
    <ConfirmAction
      label="Withdraw Consent"
      dialogLabel="Confirm consent withdrawal"
      warning="FilmDuel locks behind the consent screen until you accept the privacy policy again, and records nothing new about you in the meantime. You can still download your data or delete your account."
      confirmLabel="Yes, withdraw consent"
      pendingLabel="Withdrawing…"
      onConfirm={async () => {
        await withdrawConsent();
        window.location.href = "/";
      }}
    />
  );
}
