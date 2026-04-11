import { Film } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";

export default function Login() {
  return (
    <div className="flex items-center justify-center min-h-[80vh]">
      <Card className="w-full max-w-md text-center">
        <CardHeader className="pb-2">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
            <Film className="h-8 w-8 text-primary" />
          </div>
          <CardTitle className="text-3xl font-bold">FilmDuel</CardTitle>
          <CardDescription className="text-base">
            Rank your movies through head-to-head duels.
            <br />
            Powered by ELO ratings and your Trakt library.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          <Button size="lg" className="w-full text-base" asChild>
            <a href="/api/auth/login">Sign in with Trakt</a>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
