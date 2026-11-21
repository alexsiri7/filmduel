import AccountSettings from "../components/AccountSettings";

export default function Settings() {
  return (
    <div className="max-w-md mx-auto px-6 pt-10 pb-40">
      <h1 className="text-2xl font-headline font-black uppercase tracking-tighter mb-6">Settings</h1>
      <AccountSettings />
    </div>
  );
}
