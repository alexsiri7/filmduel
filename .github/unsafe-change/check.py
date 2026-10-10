#!/usr/bin/env python3
"""unsafe-change: denylist check for PRs built from screened public submissions.

The factory (interstellarai.net ops/cron) screens issues that public
channels file (site suggestions, Sentry events, ...) and labels the ones it
lets an agent work `archon:auto-approved`. A PR that closes such an issue
(without the owner's `archon:approved`) fails this check only if it does
something on the denylist in .github/unsafe-change.yml:

  1. touches CI/deploy/infra/agent-instruction paths (deny_paths + extra_deny_paths);
  2. touches a path naming secrets/credential/auth handling (sensitive_path_words,
     except sensitive_path_exempt: fixtures, snapshots, docs);
  3. adds a NEW dependency (name or git/path/URL source) to a manifest, or
     edits package.json "scripts" / Cargo.toml [patch]/[replace]/build;
  4. adds lines that run processes, read environment variables or open raw
     sockets (code_patterns, per file extension);
  5. adds migration SQL beyond ordinary changes in the app's own schema
     (migrations.deny_sql, schema-qualified names outside app_schemas).

Everything else passes. The factory's pr-maintenance does not merge such a
PR unless this check is green; on failure the owner reviews it.

Runs as `pull_request_target`, so this file and the policy come from the
base branch: a PR cannot weaken the check that judges it. It never checks
out or runs PR code; it reads the PR's file list, patches and manifest
contents from the API as data.

PRs that close no screened-only issue pass at once ("not applicable").

Usage (CI): GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo PR_NUMBER=n check.py
Dry run:    check.py --dry-run [--policy FILE] PR... (uses `gh auth token`,
            treats every PR as screened; prints the verdict per PR)
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY_PATH = os.path.join(HERE, "..", "unsafe-change.yml")

CLOSING_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.I)

MANIFESTS = ("Cargo.toml", "package.json", "pyproject.toml", "go.mod", "pubspec.yaml")
REQUIREMENTS_RE = re.compile(r"requirements[^/]*\.txt$")


def load_policy(path: str = POLICY_PATH) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


# ── paths ────────────────────────────────────────────────────────────────────


def glob_match(path: str, glob: str) -> bool:
    """fnmatch (`*` crosses `/`); a glob without `/` also matches the basename."""
    if fnmatch.fnmatchcase(path, glob):
        return True
    return "/" not in glob and fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], glob)


def _patch_added(patch: str | None) -> list[str]:
    return [l[1:] for l in (patch or "").splitlines() if l.startswith("+") and not l.startswith("+++")]


# ── dependencies ─────────────────────────────────────────────────────────────


def is_manifest(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base in MANIFESTS or bool(REQUIREMENTS_RE.fullmatch(base))


def _src(spec) -> str:
    """'' for a registry dependency, else a description of its git/path/URL source."""
    if isinstance(spec, dict):
        for k in ("git", "path", "url", "registry", "registry-index", "hosted", "sdk"):
            if k in spec:
                v = spec[k]
                return "%s=%s" % (k, json.dumps(v, sort_keys=True) if isinstance(v, dict) else v)
        return ""
    if isinstance(spec, str) and re.match(r"(git\+|git:|github:|gitlab:|bitbucket:|https?:|file:|link:|workspace:|npm:|[\w.-]+/[\w.-]+(#|$))", spec.strip()):
        return spec.strip()
    return ""


def _cargo(text: str) -> tuple[set[tuple[str, str]], dict]:
    doc = tomllib.loads(text)
    deps: set[tuple[str, str]] = set()
    def table(t):
        for key, spec in (t or {}).items():
            name = spec.get("package", key) if isinstance(spec, dict) else key
            deps.add((name, _src(spec)))
    tables = [doc, doc.get("workspace", {})] + list(doc.get("target", {}).values())
    for t in tables:
        for k in ("dependencies", "dev-dependencies", "build-dependencies"):
            table(t.get(k))
    special = {k: doc.get(k) for k in ("patch", "replace")}
    special["package.build"] = doc.get("package", {}).get("build")
    special["package.links"] = doc.get("package", {}).get("links")
    return deps, special


def _npm(text: str) -> tuple[set[tuple[str, str]], dict]:
    doc = json.loads(text)
    deps = set()
    for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, spec in (doc.get(k) or {}).items():
            deps.add((name, _src(spec)))
    for name in doc.get("bundleDependencies") or doc.get("bundledDependencies") or []:
        deps.add((name, ""))
    return deps, {k: doc.get(k) for k in ("scripts", "overrides", "resolutions", "pnpm", "workspaces")}


_PEP508 = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)")


def _pep508(req: str) -> tuple[str, str]:
    m = _PEP508.match(req)
    if not m:
        return (req.strip(), "unparsed")
    rest = m.group(3)
    src = rest.split("@", 1)[1].split(";")[0].strip() if rest.lstrip().startswith("@") else ""
    return (re.sub(r"[-_.]+", "-", m.group(1)).lower(), src)


def _requirements(text: str) -> tuple[set[tuple[str, str]], dict]:
    deps, special = set(), []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") or "://" in line or line.startswith((".", "/")):
            special.append(line)  # options (-r, -e, --index-url, ...) and direct URLs/paths
            continue
        deps.add(_pep508(line))
    return deps, {"options and direct URLs": sorted(special)}


def _pyproject(text: str) -> tuple[set[tuple[str, str]], dict]:
    doc = tomllib.loads(text)
    deps = set()
    proj = doc.get("project", {})
    reqs = list(proj.get("dependencies", []))
    for group in proj.get("optional-dependencies", {}).values():
        reqs += group
    for group in doc.get("dependency-groups", {}).values():
        reqs += [r for r in group if isinstance(r, str)]
    reqs += doc.get("build-system", {}).get("requires", [])
    deps |= {_pep508(r) for r in reqs}
    poetry = doc.get("tool", {}).get("poetry", {})
    tables = [poetry.get("dependencies"), poetry.get("dev-dependencies")]
    tables += [g.get("dependencies") for g in poetry.get("group", {}).values()]
    for t in tables:
        for name, spec in (t or {}).items():
            deps.add((re.sub(r"[-_.]+", "-", name).lower(), _src(spec)))
    tool = doc.get("tool", {})
    special = {"uv.sources": tool.get("uv", {}).get("sources"), "uv.index": tool.get("uv", {}).get("index"),
               "poetry.source": poetry.get("source"), "build-backend": doc.get("build-system", {}).get("build-backend")}
    return deps, special


def _gomod(text: str) -> tuple[set[tuple[str, str]], dict]:
    deps, special, block = set(), [], None
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if block:
            if line == ")":
                block = None
                continue
            words = line.split()
        else:
            m = re.match(r"(require|replace|exclude|retract|module|go|toolchain|godebug|tool)\b\s*(.*)", line)
            if not m:
                continue
            if m.group(2) == "(":
                block = m.group(1)
                continue
            block_kw, words = m.group(1), m.group(2).split()
            if block_kw == "require" and words:
                deps.add((words[0], ""))
            elif block_kw in ("replace", "tool"):
                special.append(block_kw + " " + " ".join(words))
            continue
        if block == "require" and words:
            deps.add((words[0], ""))
        elif block in ("replace", "tool"):
            special.append(block + " " + " ".join(words))
    return deps, {"replace/tool": sorted(special)}


def _pubspec(text: str) -> tuple[set[tuple[str, str]], dict]:
    doc = yaml.safe_load(text) or {}
    deps = set()
    for k in ("dependencies", "dev_dependencies"):
        for name, spec in (doc.get(k) or {}).items():
            deps.add((name, _src(spec)))
    return deps, {"dependency_overrides": doc.get("dependency_overrides")}


def parse_manifest(path: str, text: str) -> tuple[set[tuple[str, str]], dict]:
    base = path.rsplit("/", 1)[-1]
    parser = {"Cargo.toml": _cargo, "package.json": _npm, "pyproject.toml": _pyproject,
              "go.mod": _gomod, "pubspec.yaml": _pubspec}.get(base, _requirements)
    return parser(text)


def dependency_problems(path: str, base_text: str | None, head_text: str | None) -> list[str]:
    """New dependency names or sources, and changed build hooks (special keys)."""
    empty = "{}" if path.endswith("package.json") else ""
    try:
        before = parse_manifest(path, empty if base_text is None else base_text)
        after = parse_manifest(path, empty if head_text is None else head_text)
    except Exception as e:  # noqa: BLE001 — anything unparsable fails closed
        return ["%s: could not parse the manifest (%s)" % (path, type(e).__name__)]
    problems = []
    old_names = {n for n, _ in before[0]}
    new = sorted(after[0] - before[0])
    new_names = sorted({n for n, _ in new if n not in old_names})
    new_sources = ["%s (%s)" % (n, s) for n, s in new if s and n in old_names]
    if new_names:
        problems.append("%s: adds new dependencies: %s" % (path, ", ".join(new_names)))
    if new_sources:
        problems.append("%s: points dependencies at a new source: %s" % (path, ", ".join(new_sources)))
    changed = sorted(k for k, v in after[1].items() if v not in (None, [], {}, "") and v != before[1].get(k))
    if changed:
        problems.append("%s: changes %s" % (path, ", ".join(changed)))
    return problems


# ── SQL ──────────────────────────────────────────────────────────────────────


def _sql_code(text: str) -> str:
    """SQL with -- comments removed and '...' literals replaced by ''."""
    text = re.sub(r"'(?:[^']|'')*'", "''", text)
    return re.sub(r"--[^\n]*", "", text)


_QUALIFIED = re.compile(
    r"\b(FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES|ON)\s+(?:ONLY\s+)?(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
    r"\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*\.\s*\"?[A-Za-z_]", re.I)


def sql_problems(path: str, added: list[str], mig: dict) -> list[str]:
    code = _sql_code("\n".join(added))
    problems = []
    for pat in mig.get("deny_sql", []):
        m = re.search(pat, code, re.I)
        if m:
            problems.append("%s: migration does more than app-schema changes (%s)" % (path, m.group(0).strip()))
    app = {s.lower() for s in mig.get("app_schemas", [])}
    foreign = {s.lower() for s in mig.get("foreign_schemas", [])}
    bad = set()
    for kw, schema in _QUALIFIED.findall(code):
        s = schema.lower()
        if s in foreign or (kw.upper() != "ON" and app and s not in app):
            bad.add(s)
    if bad:
        problems.append("%s: migration touches schema(s) outside %s: %s" % (
            path, "/".join(sorted(app)) or "the app's", ", ".join(sorted(bad))))
    return problems


# ── evaluation (pure apart from `fetch`; unit-tested) ────────────────────────


def evaluate(files: list[dict], policy: dict, fetch=None) -> list[str]:
    """Problems with the PR's files (empty = pass).

    Each file: {filename, status, patch?, previous_filename?} as the GitHub
    pulls/files API returns them. fetch(path, "base"|"head") returns the
    file's text at that side of the PR, or None if it does not exist there;
    it is called for dependency manifests, and for files a pattern must scan
    whose patch the API left out. It may raise: that fails closed.
    """
    problems: list[str] = []
    deny = list(policy.get("deny_paths", [])) + list(policy.get("extra_deny_paths") or [])
    words = [w.lower() for w in policy.get("sensitive_path_words", [])]
    exempt = policy.get("sensitive_path_exempt") or []
    code_patterns = policy.get("code_patterns", {})
    mig = policy.get("migrations", {})

    def get(path, side):
        if fetch is None:
            raise RuntimeError("no fetcher")
        return fetch(path, side)

    for f in files:
        path, status = f["filename"], f["status"]
        paths = [path] + ([f["previous_filename"]] if f.get("previous_filename") else [])
        hit = next((g for p in paths for g in deny if glob_match(p, g)), None)
        if hit:
            problems.append("%s: CI/deploy/infra path (%s)" % (path, hit))
            continue
        word = next((w for p in paths if not any(glob_match(p, g) for g in exempt)
                     for w in words if w in p.lower()), None)
        if word:
            problems.append("%s: secrets/auth-handling path (%r)" % (path, word))
            continue
        if any(is_manifest(p) for p in paths):
            try:
                base_text = get(f.get("previous_filename") or path, "base") if status != "added" else None
                head_text = get(path, "head") if status != "removed" else None
            except Exception as e:  # noqa: BLE001
                problems.append("%s: could not read the manifest (%s)" % (path, e))
                continue
            problems += dependency_problems(path, base_text, head_text)
            continue
        if status == "removed":
            continue
        ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
        pats = code_patterns.get(ext) or []
        is_mig = any(glob_match(path, g) for g in mig.get("paths", []))
        if not pats and not is_mig:
            continue
        if f.get("patch") is not None:
            added = _patch_added(f["patch"])
        elif status == "renamed" and not f.get("changes"):
            added = []  # a pure rename adds no lines
        else:
            try:
                text = get(path, "head")
            except Exception as e:  # noqa: BLE001
                problems.append("%s: no diff and could not read the file (%s)" % (path, e))
                continue
            added = (text or "").splitlines()
        for pat in pats:
            line = next((l for l in added if re.search(pat, l)), None)
            if line is not None:
                problems.append("%s: adds process/env/socket code (%s): %.80s" % (path, pat, line.strip()))
                break
        if is_mig:
            problems += sql_problems(path, added, mig)
    return problems


def screened(issues: list[dict], policy: dict) -> list[int]:
    """Issues only automated screening vetted (no owner approval)."""
    screened_label = policy.get("screened_label", "archon:auto-approved")
    approved_label = policy.get("approved_label", "archon:approved")
    return [i["number"] for i in issues
            if screened_label in i["labels"] and approved_label not in i["labels"]]


# ── GitHub I/O ───────────────────────────────────────────────────────────────


class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token
        self.base = "https://api.github.com/repos/%s" % repo

    def api(self, url: str, data: bytes | None = None, raw: bool = False):
        req = urllib.request.Request(url if url.startswith("https:") else self.base + url, data=data, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "User-Agent": "unsafe-change-check",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode() if raw else json.load(r)

    def content(self, path: str, ref: str) -> str | None:
        try:
            return self.api("/contents/%s?ref=%s" % (urllib.parse.quote(path), ref), raw=True)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def pr_files(self, pr: int) -> list[dict]:
        files, page = [], 1
        while True:
            batch = self.api("/pulls/%d/files?per_page=100&page=%d" % (pr, page))
            files += batch
            if len(batch) < 100:
                return files
            page += 1

    def closing_issues(self, pr: int, body: str) -> list[dict]:
        owner, name = self.repo.split("/", 1)
        q = {"query": "query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p)"
                      "{closingIssuesReferences(first:20){nodes{number}}}}}",
             "variables": {"o": owner, "n": name, "p": pr}}
        gql = self.api("https://api.github.com/graphql", json.dumps(q).encode())
        numbers = {n["number"] for n in gql["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]}
        numbers |= {int(m) for m in CLOSING_RE.findall(body or "")}
        return [{"number": n, "labels": [l["name"] for l in self.api("/issues/%d" % n).get("labels", [])]}
                for n in sorted(numbers)]


def check_pr(gh: GitHub, pr: int, policy: dict, force: bool = False) -> tuple[int, list[str], str]:
    """(exit code, problems, summary line)."""
    pull = gh.api("/pulls/%d" % pr)
    nums = screened(gh.closing_issues(pr, pull.get("body") or ""), policy)
    if not nums and not force:
        return 0, [], "unsafe-change: not applicable (the PR closes no issue that only automated screening vetted)"
    files = gh.pr_files(pr)
    shas = {"base": pull["base"]["sha"], "head": pull["head"]["sha"]}
    problems = []
    if len(files) < pull.get("changed_files", 0):
        problems.append("the API listed %d of %d changed files" % (len(files), pull["changed_files"]))
    problems += evaluate(files, policy, lambda path, side: gh.content(path, shas[side]))
    closes = ", ".join("#%d" % n for n in nums) or "(none; forced)"
    if problems:
        return 1, problems, "unsafe-change: FAILED (closes %s):" % closes
    return 0, [], "unsafe-change: ok — %d file(s), nothing on the denylist (closes %s)" % (len(files), closes)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--dry-run"]:
        args = argv[1:]
        policy_path = POLICY_PATH
        if args[:1] == ["--policy"]:
            policy_path, args = args[1], args[2:]
        policy = load_policy(policy_path)
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
        repo = os.environ.get("GITHUB_REPOSITORY") or subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True, check=True).stdout.strip()
        gh = GitHub(repo, token)
        held = 0
        for n in args:
            code, problems, summary = check_pr(gh, int(n), policy, force=True)
            held += code
            print("#%s %s" % (n, "HOLD" if code else "pass"))
            for p in problems:
                print("    - " + p)
        print("%d of %d would be held" % (held, len(args)))
        return 0
    gh = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    code, problems, summary = check_pr(gh, int(os.environ["PR_NUMBER"]), load_policy())
    print(summary)
    for p in problems:
        print("  - " + p)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
