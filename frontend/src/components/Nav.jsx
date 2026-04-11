import { Link } from "react-router-dom";
import { Film, Trophy, LogOut } from "lucide-react";
import { Button } from "./ui/button";
import { logout } from "../api";

export default function Nav() {
  const handleLogout = async () => {
    await logout();
    window.location.href = "/login";
  };

  return (
    <nav className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
      <div className="container mx-auto px-4 max-w-6xl flex items-center justify-between h-14">
        <Link
          to="/"
          className="text-xl font-bold tracking-tight text-primary hover:text-primary/80 transition-colors"
        >
          FilmDuel
        </Link>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/" className="flex items-center gap-2">
              <Film className="h-4 w-4" />
              Duel
            </Link>
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/rankings" className="flex items-center gap-2">
              <Trophy className="h-4 w-4" />
              Rankings
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleLogout}
            className="text-muted-foreground hover:text-foreground"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </nav>
  );
}
