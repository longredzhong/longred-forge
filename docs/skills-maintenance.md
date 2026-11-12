# Maintaining the skills catalog

Add explicitly reviewed repositories and skills to `skill-sources.yaml`. Only
GitHub HTTPS repositories, simple branch names, and safe relative paths are
currently supported. Verify redistribution rights and the applicable license
before adding each entry. Explicitly authorized UNLICENSED sources may omit
`license_file`; this does not grant downstream reuse rights. Additional license files can be placed in the package's
recipe directory and listed under `additional_license_files`; their contents
participate in package versioning and are installed alongside the upstream license.
Setting `archive: true` pins a GitHub source archive
with a SHA-256 instead of cloning Git history; the initial archive download can
still be large. The updater queries each repository once for its ref;
when the ref or configuration changes, it also retrieves its recursive tree.
The workflow persists an optional repository cache; missing or invalid cache
causes a full tree check; a full check is repeated at least every 24 hours.
Root skills require archives and are tracked by the full repository tree.
It refuses truncated trees and source symlinks
or submodules, and validates new or changed SKILL.md frontmatter.

```sh
pixi run python scripts/skills_verify_lock.py  # offline lock/recipe consistency
pixi run skills-check             # no writes
pixi run skills-update            # update lock and recipes
pixi run python scripts/build.py --recipe-path skill-recipes/agent-skill-vercel-labs-find-skills/recipe.yaml --channel longredzhong/longred-skills-forge --target-platforms linux-64 --no-upload
```

Unrelated commits do not rebuild a skill whose directory tree and license blob
are unchanged. Changes to the license blob stop the update for manual review.
After reviewing the new license, ensure the configuration still describes the
correct license, then run `pixi run python scripts/skills_update.py --apply
--accept-license-change` to generate a new package version. Removing an entry
also requires an explicit migration.

`.github/workflows/skills-forge.yml` checks sources every three hours, builds
noarch packages, commits changed recipes and lock on `main`, and publishes using
the `SKILLS_PREFIX_TOKEN` repository secret. Its trigger and credential must be
configured on the deployed workflow; local changes alone do not activate it.
Uploads are batched and must be confirmed in channel repodata or by a fresh-cache
Pixi search with the exact channel URL, filename, and SHA-256. A package shown in
the Prefix.dev UI alone does not prove it can be resolved by Pixi.

The manager is versioned separately in `cli/pyproject.toml` and
`recipes/longred-skills/recipe.yaml`. Update both versions whenever the
manager changes; a published package filename must not be overwritten. Build
receipts include the local `cli/` source so source changes between build and
publish invalidate the receipt.
