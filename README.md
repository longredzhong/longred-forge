# longred-forge

Personal conda package repository built with [rattler-build](https://github.com/prefix-dev/rattler-build), inspired by [brad-jones/brads-forge](https://github.com/brad-jones/brads-forge).

This repository automatically builds and publishes conda packages to [prefix.dev](https://prefix.dev/channels/longred-forge), making them easily installable via conda/mamba.

## 🚀 Quick Start

**New to longred-forge?** Check out the [Quick Start Guide](QUICKSTART.md) for installation and usage instructions.

**Want to create your own forge?** See the [Configuration Guide](CONFIGURATION.md) to set up your own channel.

## 📦 Available Packages

### hatchet-cli

The Hatchet CLI for managing workflows and background tasks. Hatchet is an open-source platform for running background tasks and durable workflows at scale.

**Installation:**
```bash
# Using pixi
pixi global install -c conda-forge -c longred-forge hatchet-cli

# Using mamba/conda
mamba install -c conda-forge -c longred-forge hatchet-cli
```

**Upstream:** [hatchet-dev/hatchet](https://github.com/hatchet-dev/hatchet)

## 🚀 How It Works

1. **Automated Release Tracking**: GitHub Actions runs daily to check for new releases from upstream projects
2. **Recipe Updates**: When a new version is detected, the recipe is automatically updated
3. **Multi-Platform Builds**: Packages are built for Linux (x86_64), macOS (Intel and Apple Silicon)
4. **Publishing**: Built packages are automatically uploaded to the `longred-forge` channel on prefix.dev

## 🛠️ Technical Details

This repository uses:
- **rattler-build**: Fast, modern conda package builder
- **GitHub Actions**: Automated CI/CD pipeline
- **prefix.dev**: Package hosting and distribution

### Project Structure

```
longred-forge/
├── recipes/
│   └── hatchet-cli/
│       └── recipe.yaml          # Package recipe
├── .github/
│   └── workflows/
│       └── build-hatchet-cli.yml # CI/CD workflow
└── README.md
```

## 🔧 Adding New Packages

To add a new package:

1. Create a new recipe directory under `recipes/`
2. Add a `recipe.yaml` file following the [rattler-build format](https://rattler-build.prefix.dev/)
3. Create a corresponding GitHub Actions workflow in `.github/workflows/`

Example recipe structure:
```yaml
context:
  version: "1.0.0"

package:
  name: my-package
  version: ${{ version }}

source:
  url: https://github.com/owner/repo/releases/download/v${{ version }}/package.tar.gz

build:
  number: 0
  script:
    - mkdir -p $PREFIX/bin
    - cp binary $PREFIX/bin/

about:
  homepage: https://example.com
  license: MIT
  summary: Package description
```

## 📝 License

This repository is licensed under the MIT License. Individual packages may have their own licenses.

## 🙏 Acknowledgments

- Inspired by [brad-jones/brads-forge](https://github.com/brad-jones/brads-forge)
- Built with [rattler-build](https://github.com/prefix-dev/rattler-build) by [prefix.dev](https://prefix.dev)
- Packages from upstream projects maintain their original licenses and authorship