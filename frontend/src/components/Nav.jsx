import { Link } from "react-router-dom";
import { logout } from "../api";

export default function Nav() {
  const handleLogout = async () => {
    await logout();
    window.location.href = "/login";
  };

  return (
    <nav className="navbar">
      <Link to="/" className="nav-brand">
        FilmDuel
      </Link>
      <div className="nav-links">
        <Link to="/">Duel</Link>
        <Link to="/rankings">Rankings</Link>
        <button onClick={handleLogout} className="nav-logout">
          Logout
        </button>
      </div>
    </nav>
  );
}
