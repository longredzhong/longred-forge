# Configuration Guide

## Setting Up Your Own Fork

If you want to create your own personal forge based on this project, follow these steps:

### 1. Create a Channel on prefix.dev

1. Go to [prefix.dev](https://prefix.dev) and sign in with your GitHub account
2. Navigate to "Channels" and create a new channel (e.g., `your-username-forge`)
3. Note your channel name for later use

### 2. Configure Publishing Authentication

The current build script uses a prefix.dev API token, not OIDC. Create a token with write access to your channel and save it as the GitHub Actions repository secret `PREFIX_TOKEN`. Local publishing also accepts `PREFIX_API_KEY`. Missing credentials fail publishing; use `--no-upload` for local build-only checks.

### 3. Update Workflow Configuration

The build workflow is [main.yaml](.github/workflows/main.yaml). Set your channel using `--channel your-channel` in its build command (the default is `longred-forge`).

### 4. Test the Workflow

1. Push changes to the `main` branch or manually trigger the workflow
2. Check the Actions tab to see the build progress
3. Once complete, verify the package appears in your prefix.dev channel

## Local Development

### Prerequisites

Install [pixi](https://pixi.sh/):
```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

### Building Locally

```bash
# Build without publishing
pixi run build --recipe-path recipes/hatchet-cli/recipe.yaml --no-upload

# Run regression tests and maintenance checks
pixi run test
pixi run validate
pixi run lint

# Preview upstream updates
pixi run update --dry-run
```

`pixi run validate` renders every recipe against all five target platforms: currently 12 recipes × 5
platforms = 60 render checks, including unsupported/skipped combinations. It does not build packages.

### Incremental Builds and Reports

```bash
# Build recipes affected by committed changes between REF and HEAD, without publishing
pixi run build --changed-since REF --no-upload --report output/build-results.json

# Publish previously built exact artifacts and write a separate results manifest
pixi run build --recipe-path recipes/hatchet-cli/recipe.yaml --no-build --report output/publish-results.json
```

`--changed-since REF` compares `REF` with `HEAD`, not uncommitted changes. Changes anywhere inside a
recipe directory select that recipe; changes under `scripts/`, `tests/`, or `.github/`, or to
`pixi.toml`/`pixi.lock`, select all recipes. An explicit `--recipe-path` takes precedence.
`--report path` writes machine-readable per-recipe/platform results, including artifact outcomes and
failures; remaining recipes continue after a failure, and the batch exits nonzero if any fail.

`--no-build` renders the original recipe to determine exact package filenames and looks only for those
artifacts under `output/<platform>/`; it does not upload arbitrary matching files. Each package requires
a companion builder-generated receipt: `name-version-build.conda` must have
`name-version-build.receipt.json` containing its filename and matching SHA256. Missing or mismatched
receipts fail the operation; rebuild rather than manufacturing receipts. Retain receipts alongside
packages when transferring build outputs. `--skip-existing` can skip artifacts already in the public
channel index before requiring local files.

### Module Architecture

`scripts/build.py` is the CLI entry point. The refactored `scripts/forge/` modules separate rendered
artifact identities and changed-recipe selection (`planner.py`), original-path builds and receipt
checks (`builder.py`), upload and public-index verification (`publisher.py`), and result manifests and
Actions summaries (`reporting.py`). Updater support is separated into upstream asset resolution
(`upstream.py`) and shared HTTP handling (`http.py`), with `scripts/update.py` as its CLI entry point.

### Manual Build with rattler-build

```bash
# Install rattler-build
pixi global install rattler-build

# Build a specific recipe
rattler-build build --recipe recipes/hatchet-cli

# Test the package
rattler-build test --package-file output/*.conda
```

## Adding New Packages

### 1. Create Recipe

Create a new directory under `recipes/` with a `recipe.yaml` file:

```yaml
context:
  version: "1.0.0"

package:
  name: my-package
  version: ${{ version }}

source:
  url: https://example.com/package-${{ version }}.tar.gz
  # Replace with the verified 64-character SHA256 checksum of the source
  sha256: <verified-sha256>

build:
  number: 0
  script:
    - if: win
      then: python "%RECIPE_DIR%/install.py"
      else: python "$RECIPE_DIR/install.py"

requirements:
  build:
    - python
  run:
    - dependency1
    - dependency2

tests:
  - script:
      - my-package --version

about:
  homepage: https://example.com
  license: MIT
  summary: Short description
  repository: https://github.com/owner/repo
```

Create an adjacent `install.py` that copies the upstream binary into `PREFIX/bin` on Unix or
`PREFIX/Scripts` on Windows and sets executable permissions on Unix. The build task runs
`python scripts/build.py` against the original recipe path, preserving access to local resources.
Use `build.skip` to exclude platforms without upstream assets.

### 2. Reuse the Workflows

[main.yaml](.github/workflows/main.yaml) builds and publishes recipes. Its push paths include
`recipes/**`, `scripts/**`, `tests/**`, `pixi.toml`, `pixi.lock`, and the workflow itself.
[auto-update.yml](.github/workflows/auto-update.yml) checks releases every three hours and dispatches
`main.yaml` after committing recipe updates. No per-package publish workflow is needed.

### 3. Test Locally

```bash
pixi run build --recipe-path recipes/my-package/recipe.yaml --no-upload
```

## Workflow Features

### Automatic Release Tracking

The workflow checks every three hours (at minute 10) for new releases from the upstream project. When a new version is detected:
1. The recipe is automatically updated
2. The package is built for supported platforms
3. Built packages are published to prefix.dev

### Manual Triggering

You can manually trigger a build:
1. Go to the Actions tab in your repository
2. Select the workflow
3. Configure the manual inputs and click "Run workflow":
   - `recipe`: recipe directory name, such as `hatchet-cli`; empty selects all recipes.
   - `publish`: whether to publish built artifacts (default `true`). Publishing is restricted to
     non-pull-request runs on `main`, and credentials are provided only to the publishing step.
   - `force_rebuild`: rebuild even when a package already exists (default `false`). Intended for use
     with `publish=false` to test rebuilding; it does not authorize overwriting published packages.

The build step runs without publishing credentials and writes `output/build-results.json`. A separate
`--no-build` publishing step verifies builder receipts and writes `output/publish-results.json`.
GitHub Actions retains packages, receipts, result manifests, and the build log (when present) as
per-platform workflow artifacts for **7 days**, including after failures.

### Publishing Verification and Retries

Publishing computes the local package SHA256 and checks the public index at
`https://repo.prefix.dev/<channel>/<platform>/repodata.json`. An existing exact filename with the same
SHA256 is reported as `already_exists`; a differing SHA256 fails with an instruction to increment
`build.number`, rather than replacing the published package. After upload, success requires that the
public index contains the exact filename and matching SHA256; upload success alone is not sufficient.

Failed upload commands are retried up to three attempts, with 1- and 2-second backoffs. After a
successful upload, indexing is checked up to six times with bounded exponential waits (up to 8 seconds
per wait). Failure to observe the indexed artifact fails publishing. HTTP/index errors and checksum
mismatches are surfaced as errors, not silently treated as successful uploads.

### Multi-Platform Builds

The workflow builds packages for:
- Linux x86_64
- Linux aarch64 (ARM64)
- macOS Intel (x86_64)
- macOS Apple Silicon (arm64)
- Windows x86_64

Availability depends on each recipe’s upstream assets and `build.skip` conditions; not every package
is available on every platform. Cross-platform render checks do not replace native build tests.

## Independent Major-Version Lines

Recipes can set `extra.update.major` to a positive integer to select the highest stable numeric `vMAJOR.MINOR.PATCH` release within that major. The updater paginates GitHub releases, excludes draft/prerelease/component tags, and refuses downgrades. Without this setting, the existing GitHub latest-release behavior is retained.

```yaml
extra:
  update:
    major: 2
```

`opencode` tracks major 1; `opencode2` tracks major 2 and installs only the `opencode2` command. Separate command names do not imply isolated application state. GitHub release scans should use `GITHUB_TOKEN` to avoid anonymous API rate limits.

## Troubleshooting

### Build Failures

Unsupported platforms must be excluded with recipe `build.skip` selectors (for example, `win` or `not linux`). A conditional source alone does not skip a recipe. The build runner continues other recipes after a failure, records failures in the Actions summary, and exits nonzero after the batch.

If upstream assets change without a new version, explicitly refresh checksums after reviewing the release assets:

```bash
pixi run update --recipe recipes/obscura/recipe.yaml --refresh-checksums --dry-run
pixi run update --recipe recipes/obscura/recipe.yaml --refresh-checksums --apply
```

Checksum refresh is opt-in. Failed asset resolution leaves the recipe unchanged. If changed assets have already been published under the same version, increment `build.number` before republishing.

Run publishing regression tests with `pixi run test`.

1. Check the Actions logs for specific errors
2. Verify the source URL is accessible
3. Check that dependencies are available in conda-forge
4. Test the build locally with `pixi run build --recipe-path recipes/hatchet-cli/recipe.yaml --no-upload`

### Publishing Failures

1. Verify your prefix.dev credentials are configured correctly
2. Check that the channel name matches in the workflow
3. Ensure you have write permissions to the channel
4. Verify `PREFIX_TOKEN` (or locally `PREFIX_API_KEY`) is present and has channel write access

### Version Detection Issues

If the workflow doesn't detect new versions:
1. Check the upstream release API endpoint
2. Verify the version parsing in the workflow
3. Manually trigger the workflow to force a build

## Resources

- [rattler-build Documentation](https://rattler-build.prefix.dev/)
- [prefix.dev Documentation](https://prefix.dev/docs)
- [pixi Documentation](https://pixi.sh/latest/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
