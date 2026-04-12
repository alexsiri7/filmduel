import { Link, useLocation } from "react-router-dom";
import { logout } from "../api";

const navItems = [
  { path: "/", label: "Current Duel", icon: "swords" },
  { path: "/swipe", label: "Swipe", icon: "swipe" },
  { path: "/rankings", label: "Rankings", icon: "leaderboard" },
  { path: "/tournaments", label: "Tournaments", icon: "bracket" },
];

export default function Nav() {
  const location = useLocation();

  const handleLogout = async () => {
    await logout();
    window.location.href = "/login";
  };

  return (
    <aside className="fixed left-0 top-0 h-full w-64 z-40 bg-[#141312] shadow-[10px_0_30px_rgba(0,0,0,0.3)] hidden md:flex flex-col py-8 px-4 gap-8">
      {/* Logo */}
      <div className="flex items-center gap-3 px-2">
        <div className="w-10 h-10 flex items-center justify-center">
          <img src="/logo.png" alt="FilmDuel" className="w-10 h-10 object-contain" />
        </div>
        <div>
          <h1 className="text-[#E8A020] text-xl font-black font-headline tracking-tighter uppercase">
            FILMDUEL
          </h1>
          <p className="text-[#F5F0E8]/40 text-[10px] uppercase tracking-[0.2em] font-bold">
            The Noir Projectionist
          </p>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 space-y-2">
        {navItems.map((item) => {
          const isActive =
            item.path === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={
                isActive
                  ? "flex items-center gap-4 px-4 py-3 bg-[#E8A020] text-[#0F0E0D] rounded-none shadow-[0_0_15px_rgba(232,160,32,0.3)] font-headline font-bold uppercase tracking-wider transition-all duration-300"
                  : "flex items-center gap-4 px-4 py-3 text-[#F5F0E8]/40 hover:text-[#F5F0E8] hover:bg-[#1d1b1a] font-headline font-bold uppercase tracking-wider transition-all hover:translate-x-1 duration-300"
              }
            >
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Actions */}
      <div className="px-2 space-y-3">
        <Link
          to="/"
          className="block w-full bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase py-4 tracking-widest text-sm text-center hover:scale-[1.02] active:scale-95 transition-all"
        >
          START DUEL
        </Link>
        <a
          href="https://github.com/alexsiri7/filmduel/issues/new?labels=feedback&title=Feedback:+&body=Describe+the+issue+or+suggestion..."
          target="_blank"
          rel="noopener noreferrer"
          className="block w-full text-center text-[#F5F0E8]/30 hover:text-[#E8A020]/70 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
        >
          Report Issue
        </a>
        <button
          onClick={handleLogout}
          className="w-full text-[#F5F0E8]/30 hover:text-[#F5F0E8]/60 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
        >
          Sign Out
        </button>
      </div>
    </aside>
  );
}
