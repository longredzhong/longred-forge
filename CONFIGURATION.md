# Configuration Guide

## Setting Up Your Own Fork

If you want to create your own personal forge based on this project, follow these steps:

### 1. Create a Channel on prefix.dev

1. Go to [prefix.dev](https://prefix.dev) and sign in with your GitHub account
2. Navigate to "Channels" and create a new channel (e.g., `your-username-forge`)
3. Note your channel name for later use

### 2. Configure OIDC Authentication (Recommended)

OIDC (OpenID Connect) allows GitHub Actions to authenticate with prefix.dev without storing API keys.

1. In your prefix.dev channel settings, go to "Trusted Publishers"
2. Add a new trusted publisher with:
   - **Provider**: GitHub Actions
   - **Repository**: your-username/your-repo-name
   - **Workflow**: `.github/workflows/build-hatchet-cli.yml`
   - **Environment**: (leave empty or specify if you use environments)

### 3. Alternative: API Key Authentication

If you prefer using an API key:

1. Generate an API key in your prefix.dev account settings
2. Add it as a repository secret in GitHub:
   - Go to your repository Settings → Secrets and variables → Actions
   - Add a new secret named `PREFIX_API_KEY`
   - Paste your prefix.dev API key as the value

### 4. Update Workflow Configuration

Edit `.github/workflows/build-hatchet-cli.yml` and replace:
- `longred-forge` with your channel name in the publish step

### 5. Test the Workflow

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
# Build the package
pixi run build

# Test the built package
pixi run test
```

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
  sha256: <checksum>

build:
  number: 0
  script:
    - mkdir -p $PREFIX/bin  # [unix]
    - cp binary $PREFIX/bin/  # [unix]

requirements:
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

### 2. Create Workflow

Copy and modify `.github/workflows/build-hatchet-cli.yml`:
- Update the workflow name
- Update paths to your recipe
- Adjust the release checking logic if needed
- Update the schedule if desired

### 3. Test Locally

```bash
pixi run build --recipe recipes/my-package
```

## Workflow Features

### Automatic Release Tracking

The workflow checks daily for new releases from the upstream project. When a new version is detected:
1. The recipe is automatically updated
2. The package is built for all platforms
3. Built packages are published to prefix.dev

### Manual Triggering

You can manually trigger a build:
1. Go to the Actions tab in your repository
2. Select the workflow
3. Click "Run workflow"

### Multi-Platform Builds

The workflow builds packages for:
- Linux x86_64
- macOS Intel (x86_64)
- macOS Apple Silicon (arm64)

## Troubleshooting

### Build Failures

1. Check the Actions logs for specific errors
2. Verify the source URL is accessible
3. Check that dependencies are available in conda-forge
4. Test the build locally with `pixi run build`

### Publishing Failures

1. Verify your prefix.dev credentials are configured correctly
2. Check that the channel name matches in the workflow
3. Ensure you have write permissions to the channel
4. For OIDC: verify the trusted publisher configuration

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
