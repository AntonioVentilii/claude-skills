# claude-skills

My personal, version-controlled [Claude Code Agent Skills](https://docs.claude.com/en/docs/claude-code/skills).
This repo is the **durable home** for skills so they're never lost: the source
of truth lives here (in git, pushed to GitHub), and each skill is **symlinked**
into `~/.claude/skills/` so Claude Code loads it locally.

## Skills

- **`prototype-to-app-port/`** — methodology for porting a design prototype (or a
  new prototype version) into a production codebase with high fidelity. Stack-
  agnostic core + swappable per-project profiles (e.g. `project-profile-vici.md`).
- **`sapiens/`** — concise-but-complete communication mode. The middle ground
  between [caveman](https://github.com/JuliusBrussee/caveman) (too lossy) and
  default verbosity (too prolisso): keeps explanations, caveats, and findings
  while cutting preamble and padding. Language-agnostic. Trigger with `/sapiens`.
- **`merge-queue/`** — a merge queue for repos without GitHub's native one
  (personal repos, private repos on Free/Team). PRs into the default branch
  only, oldest-first, one at a time: ready-for-review → Copilot review handled
  (green/blue/yellow; blue ones confirmed with you) → approvals → update with
  main (GitHub's Update branch, merge commit by default) → CI green → merge (squash, direct by default; auto-merge opt-in).
  Shows a briefing and waits for a go-ahead first, then touches only the PRs
  you approved; skips anything not ready, ignores release PRs, ends with a
  report. Default: only your PRs. Per-repo defaults in
  `merge-queue/config/repos.json`; needs an authenticated `gh`. Trigger with
  `/merge-queue` (`/merge-queue all`, `/merge-queue #12 #15`, `dry run`, …).

## Install on a machine (or after a fresh clone)

```bash
git clone https://github.com/AntonioVentilii/claude-skills.git ~/projects/claude-skills
mkdir -p ~/.claude/skills
# symlink each skill into the user skills dir:
ln -s ~/projects/claude-skills/prototype-to-app-port ~/.claude/skills/prototype-to-app-port
ln -s ~/projects/claude-skills/sapiens ~/.claude/skills/sapiens
ln -s ~/projects/claude-skills/merge-queue ~/.claude/skills/merge-queue
```

Claude Code reads skills from `~/.claude/skills/`. Because each entry is a
symlink back to this repo, editing here updates the live skill, and `git push`
keeps it backed up + syncable across machines.

## Add or edit a skill

1. Edit files under the skill folder here (this repo).
2. Commit + push — that's the backup.
3. New skill? Create its folder, then symlink it into `~/.claude/skills/`.

## Future: share as a plugin

This repo can double as a Claude Code **plugin marketplace** when you want to
share skills with a team — the same folders install via the plugin system from
the git URL. No restructuring needed to start; add a marketplace manifest when
that day comes.
