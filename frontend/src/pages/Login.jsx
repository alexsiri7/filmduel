export default function Login() {
  return (
    <div className="login-page">
      <h1>FilmDuel</h1>
      <p>Rank your movies through head-to-head duels.</p>
      <a href="/api/auth/login" className="login-button">
        Sign in with Trakt
      </a>
    </div>
  );
}
