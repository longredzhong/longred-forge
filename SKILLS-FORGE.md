# Longred Skills Forge

Skill packages are published to `https://prefix.dev/longredzhong/longred-skills-forge`.
The `longred-skills` manager is published separately to the main
`https://prefix.dev/longred-forge` channel.
The initial catalog contains `find-skills` from `vercel-labs/skills` plus five
skills from `github/awesome-copilot`, distributed under their upstream MIT
licenses. The lock records the exact Git commit, skill subtree, license blob,
and package version for each skill.

`agent-skill-litestar-org-litestar-skills` contains the 20 Litestar skills as a
single package: their documentation links to other skills in the same group.
`agent-skill-tiangolo-library-skills` contains the `library-skills` instructions;
the separate upstream CLI referenced by those instructions is not installed by
the skill package. Turnpike's Cloudflare and TypeScript clean-code skills are
fixed to commits that match its original `skills-lock.json` contents. Their
source lock hashes are recorded and verified against the complete upstream
skill directories using the `npx skills` hashing algorithm. Node.js supplies
the same `localeCompare` ordering and is installed by the Pixi environment.
`design-taste-frontend` follows the upstream main branch. Its previously pinned
Turnpike snapshot has been replaced by the current skill; existing consumers
that need the old behavior should retain their previous lock. Its mixed-license
notices remain in the package. `impeccable` packages upstream's `.agents` build,
including its references, launcher and third-party notice; its native engine is
obtained separately by the upstream launcher. The upstream Claude-specific
build has different instructions and is not provided by this package.
`simplify-codebase` is a repository-root skill, packaged from a commit archive.

Package versions such as `0.0.2` are monotonic catalog revisions, not upstream
release versions. The lock records the exact source commit and skill tree. A
skill tree, license or packaging identity change increments the package revision;
a repository commit that leaves those unchanged does not. Inspect upstream
release tags and skill metadata separately when reporting upstream versions.
Additional domain packages include Addy Osmani's frontend UI guidance,
Wshobson's Python development skill bundle, K-Dense's exploratory analysis
and scientific visualization skills, and the presentation-agent-skills bundle.
The presentation bundle includes upstream third-party notices. PPTX creation,
rendering and visual QA require the separately installed tools documented by
the skills; scientific tools may require optional Python dependencies.

Popular skills are selected from the skills.sh all-time leaderboard and locked
at reviewed upstream commits. Matt Pocock's interview and architecture commands
install their referenced sibling skills as dependencies. `agent-browser` is an
upstream discovery stub: its separately installed, version-matched CLI supplies
the actual guides and browser runtime. Anthropic's frontend-design license is
stored inside its skill directory. The Supabase Postgres skill includes its rules.
Minimum-version skill dependencies accept newer package revisions; exact-version
dependencies continue to require the specified revision.

The `cloudflare` skill package declares its `durable-objects` and
`nextjs-on-cloudflare` sibling skills as exact runtime dependencies, so relative
references resolve inside the same Pixi environment.

Once the manager is indexed in the main channel, install it with:

```sh
pixi global install -c https://prefix.dev/longred-forge -c conda-forge longred-skills
```

In a project that already has a Pixi workspace:

```sh
longred-skills find find-skills
# Direct or friendly short name resolution:
longred-skills add find-skills
longred-skills info find-skills
longred-skills list -v
longred-skills sync --agent all

# Update skills and re-sync
longred-skills update

# Remove package and automatically prune agent symlinks
longred-skills remove find-skills

# The entire Litestar group, including cross-referenced skills
longred-skills add agent-skill-litestar-org-litestar-skills --agent codex

# Turnpike's pinned frontend design skill and its attributed assets
longred-skills add agent-skill-leonxlnx-design-taste-frontend --agent codex
```

`add` adds the channel and package to the selected Pixi environment, resolves
the lockfile, and creates relative symlinks under `.agents/skills` by default.
Pass `--agent all` or comma-separated agents (e.g. `--agent claude,cursor,codex`)
to link into multiple agent targets simultaneously (`agents`, `claude`, `codex`,
`cursor`, `cline`, `windsurf`). Commands locate the nearest Pixi workspace when run from a
subdirectory, including workspaces configured in `pyproject.toml`.
`remove` removes the package from Pixi and automatically unlinks stale agent symlinks.
`sync` can be rerun anytime (including after `pixi install --locked`) and automatically
prunes dangling symlinks pointing to deleted Pixi environment targets.
Existing files or links to another non-Pixi target cause an error and are never overwritten.
Already installed skills are checked for destination conflicts before `add`
changes the Pixi project. If a conflict is only discoverable after installing
a new package, the command reports that the manifest, lockfile and environment
may already have changed; resolve the conflict and rerun `sync`.
Use `longred-skills add --global PACKAGE` to install into a persistent workspace
under `~/.local/share/longred-skills/default` (or `$XDG_DATA_HOME`/`%LOCALAPPDATA%`) and link into `~/.agents/skills`.
Run `longred-skills sync --global --agent all` to link the same installed
skills into all supported user agent directories; `list --global` lists installed skills. Named
`--environment` values select separate global workspaces. Existing destination
conflicts are never overwritten, including links from another environment.

To bootstrap a cloned repository with all skills immediately linked:

```sh
pixi run setup
```

## Maintaining the catalog

See [Skills catalog maintenance](docs/skills-maintenance.md) for source review, versioning, CI and publication procedures.
