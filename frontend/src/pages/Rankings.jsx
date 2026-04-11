import { useState, useEffect, useCallback } from "react";
import { Download, Trophy, Swords, BarChart3 } from "lucide-react";
import { getRankings, getStats } from "../api";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardContent } from "../components/ui/card";

function RankingsSkeleton() {
  return (
    <div className="skeleton-rankings">
      <div className="skeleton-rankings-header">
        <div className="skeleton skeleton-header" />
        <div className="skeleton" style={{ height: 32, width: 100, borderRadius: 8 }} />
      </div>
      <div className="skeleton-stats">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton skeleton-stat-card" />
        ))}
      </div>
      <div>
        <div className="skeleton skeleton-table-header" />
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <div key={i} className="skeleton skeleton-row" />
        ))}
      </div>
    </div>
  );
}

export default function Rankings() {
  const [rankings, setRankings] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rankData, statsData] = await Promise.all([
        getRankings(),
        getStats(),
      ]);
      setRankings(rankData.rankings);
      setStats(statsData);
    } catch (err) {
      console.error("Failed to load rankings:", err);
      setError(err.message || "Could not load rankings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <RankingsSkeleton />;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <p className="text-muted-foreground">{error}</p>
        <Button variant="outline" onClick={load}>
          Try Again
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight">Your Rankings</h2>
        <Button variant="outline" size="sm" asChild className="gap-2">
          <a href="/api/rankings/export/csv" download>
            <Download className="h-4 w-4" />
            Export CSV
          </a>
        </Button>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <Trophy className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.total_movies_ranked}</p>
                <p className="text-xs text-muted-foreground">Movies Ranked</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <Swords className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.total_duels}</p>
                <p className="text-xs text-muted-foreground">Duels Completed</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <BarChart3 className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-2xl font-bold">{Math.round(stats.average_elo)}</p>
                <p className="text-xs text-muted-foreground">Average ELO</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Rankings table */}
      {rankings.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            No rankings yet. Start dueling to build your list!
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-xl border border-border overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-card border-b border-border">
                <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider w-12">
                  #
                </th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Title
                </th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider w-20 hidden sm:table-cell">
                  Year
                </th>
                <th className="text-right p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider w-20">
                  ELO
                </th>
                <th className="text-right p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider w-20 hidden sm:table-cell">
                  Duels
                </th>
              </tr>
            </thead>
            <tbody>
              {rankings.map((r) => (
                <tr
                  key={r.movie.id}
                  className="border-b border-border/50 hover:bg-card/50 transition-colors"
                >
                  <td className="p-3">
                    {r.rank <= 3 ? (
                      <Badge variant={r.rank === 1 ? "default" : "secondary"}>
                        {r.rank}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-sm">
                        {r.rank}
                      </span>
                    )}
                  </td>
                  <td className="p-3 font-medium">{r.movie.title}</td>
                  <td className="p-3 text-muted-foreground text-sm hidden sm:table-cell">
                    {r.movie.year}
                  </td>
                  <td className="p-3 text-right font-mono text-sm font-semibold">
                    {r.elo}
                  </td>
                  <td className="p-3 text-right text-muted-foreground text-sm hidden sm:table-cell">
                    {r.battles}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
