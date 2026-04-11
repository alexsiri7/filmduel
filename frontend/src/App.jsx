import { Routes, Route } from "react-router-dom";
import Nav from "./components/Nav";
import Login from "./pages/Login";
import Duel from "./pages/Duel";
import Rankings from "./pages/Rankings";

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Nav />
      <main className="container mx-auto px-4 py-8 max-w-6xl">
        <Routes>
          <Route path="/" element={<Duel />} />
          <Route path="/login" element={<Login />} />
          <Route path="/rankings" element={<Rankings />} />
        </Routes>
      </main>
    </div>
  );
}
