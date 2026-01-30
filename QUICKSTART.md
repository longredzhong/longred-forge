# Quick Start Guide

This guide will help you get started with longred-forge, whether you're using packages or forking the project.

## Using Packages from longred-forge

### Installation

#### Option 1: Using pixi (Recommended)

```bash
# Install pixi if you haven't already
curl -fsSL https://pixi.sh/install.sh | bash

# Install hatchet-cli globally
pixi global install -c conda-forge -c longred-forge hatchet-cli

# Verify installation
hatchet --version
```

#### Option 2: Using mamba/conda

```bash
# Install mamba if you haven't already (much faster than conda)
conda install -c conda-forge mamba

# Install hatchet-cli
mamba install -c conda-forge -c longred-forge hatchet-cli

# Verify installation
hatchet --version
```

#### Option 3: Creating a project environment

Create a `pixi.toml` file:

```toml
[project]
name = "my-project"
channels = ["conda-forge", "longred-forge"]
platforms = ["linux-64", "osx-64", "osx-arm64"]

[dependencies]
hatchet-cli = "*"
```

Then run:
```bash
pixi install
pixi run hatchet --version
```

### Using in a conda environment

```bash
# Create a new environment
mamba create -n myenv -c conda-forge -c longred-forge hatchet-cli

# Activate the environment
conda activate myenv

# Use the tool
hatchet --version
```

## Forking longred-forge

### 1. Fork and Clone

```bash
# Fork on GitHub, then clone your fork
git clone https://github.com/YOUR-USERNAME/YOUR-FORK-NAME.git
cd YOUR-FORK-NAME
```

### 2. Set Up prefix.dev

1. Go to [prefix.dev](https://prefix.dev)
2. Sign in with your GitHub account
3. Create a new channel (e.g., `your-username-forge`)
4. Set up OIDC authentication:
   - Go to channel settings → Trusted Publishers
   - Add GitHub Actions as a trusted publisher
   - Repository: `YOUR-USERNAME/YOUR-FORK-NAME`
   - Workflow: `.github/workflows/build-hatchet-cli.yml`

### 3. Update Configuration

Edit `.github/workflows/build-hatchet-cli.yml`:

```yaml
# Find this line in the publish-package job:
rattler-build upload prefix -c longred-forge "$pkg"

# Replace with your channel name:
rattler-build upload prefix -c your-username-forge "$pkg"
```

### 4. Test Locally

```bash
# Install pixi
curl -fsSL https://pixi.sh/install.sh | bash

# Build the package
pixi run build

# The built package will be in the output/ directory
ls -lh output/
```

### 5. Push and Deploy

```bash
git add .
git commit -m "Configure for my channel"
git push

# The GitHub Actions workflow will automatically:
# 1. Check for new releases daily
# 2. Build packages for all platforms
# 3. Publish to your prefix.dev channel
```

### 6. Install from Your Channel

```bash
pixi global install -c conda-forge -c your-username-forge hatchet-cli
```

## Adding More Packages

### 1. Create a Recipe

```bash
mkdir -p recipes/new-package
```

Create `recipes/new-package/recipe.yaml`:

```yaml
context:
  version: "1.0.0"

package:
  name: new-package
  version: ${{ version }}

source:
  url: https://github.com/owner/repo/releases/download/v${{ version }}/binary.tar.gz
  sha256: skip

build:
  number: 0
  script:
    - mkdir -p $PREFIX/bin
    - cp binary $PREFIX/bin/

tests:
  - script:
      - binary --version

about:
  homepage: https://example.com
  license: MIT
  summary: Package description
  repository: https://github.com/owner/repo
```

### 2. Create a Workflow

Copy and modify `.github/workflows/build-hatchet-cli.yml`:

```bash
cp .github/workflows/build-hatchet-cli.yml .github/workflows/build-new-package.yml
```

Update:
- Workflow name
- Recipe path
- Release checking logic
- Package name

### 3. Test

```bash
pixi run build --recipe recipes/new-package
```

### 4. Commit and Push

```bash
git add recipes/new-package .github/workflows/build-new-package.yml
git commit -m "Add new-package recipe"
git push
```

## Troubleshooting

### Build Failures

**Issue**: Package fails to build

**Solutions**:
1. Check the Actions logs for detailed errors
2. Test locally: `pixi run build --recipe recipes/package-name`
3. Verify the source URL is accessible
4. Check that all dependencies are available

### Installation Issues

**Issue**: Package not found

**Solutions**:
1. Verify you're using the correct channel: `-c longred-forge`
2. Check if the package exists: `mamba search -c longred-forge package-name`
3. Clear conda cache: `conda clean --all`

### OIDC Authentication

**Issue**: Publishing fails with authentication error

**Solutions**:
1. Verify trusted publisher is configured correctly on prefix.dev
2. Check repository name matches exactly
3. Ensure workflow permissions include `id-token: write`

## Next Steps

- Read the [full README](README.md) for more details
- Check [CONFIGURATION.md](CONFIGURATION.md) for advanced setup
- See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute

## Getting Help

- Check existing [issues](https://github.com/longredzhong/longred-forge/issues)
- Open a new issue with details about your problem
- Include error messages and relevant configuration
