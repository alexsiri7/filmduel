import { Routes, Route } from "react-router-dom";
import Nav from "./components/Nav";
import Login from "./pages/Login";
import Duel from "./pages/Duel";
import Rankings from "./pages/Rankings";

export default function App() {
  return (
    <div className="app">
      <Nav />
      <main>
        <Routes>
          <Route path="/" element={<Duel />} />
          <Route path="/login" element={<Login />} />
          <Route path="/rankings" element={<Rankings />} />
        </Routes>
      </main>
    </div>
  );
}
