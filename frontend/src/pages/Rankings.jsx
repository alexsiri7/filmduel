import { useState, useEffect } from "react";
import { getRankings, getStats } from "../api";

export default function Rankings() {
  const [rankings, setRankings] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [rankData, statsData] = await Promise.all([
          getRankings(),
          getStats(),
        ]);
        setRankings(rankData.rankings);
        setStats(statsData);
      } catch (err) {
        console.error("Failed to load rankings:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <div>Loading rankings...</div>;

  return (
    <div className="rankings-page">
      <h2>Your Rankings</h2>

      {stats && (
        <div className="stats-summary">
          <span>{stats.total_movies_ranked} movies ranked</span>
          <span>{stats.total_duels} duels completed</span>
          <span>Avg ELO: {stats.average_elo}</span>
        </div>
      )}

      <div className="rankings-actions">
        <a href="/api/rankings/export/csv" download className="export-btn">
          Export CSV (Letterboxd)
        </a>
      </div>

      <table className="rankings-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Title</th>
            <th>Year</th>
            <th>ELO</th>
            <th>Duels</th>
            <th>Wins</th>
          </tr>
        </thead>
        <tbody>
          {rankings.map((r) => (
            <tr key={r.movie.id}>
              <td>{r.rank}</td>
              <td>{r.movie.title}</td>
              <td>{r.movie.year}</td>
              <td>{Math.round(r.elo_rating)}</td>
              <td>{r.duel_count}</td>
              <td>{r.win_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
