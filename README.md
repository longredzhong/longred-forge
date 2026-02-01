# longred-forge

Personal conda package repository built with [rattler-build](https://github.com/prefix-dev/rattler-build), inspired by [brad-jones/brads-forge](https://github.com/brad-jones/brads-forge).

This repository automatically builds and publishes conda packages to [prefix.dev](https://prefix.dev/channels/longred-forge), making them easily installable via conda/mamba.

## 🚀 Quick Start

**New to longred-forge?** Check out the [Quick Start Guide](QUICKSTART.md) for installation and usage instructions.

**Want to create your own forge?** See the [Configuration Guide](CONFIGURATION.md) to set up your own channel.

## 📦 Available Packages

### hatchet-cli

The Hatchet CLI for managing workflows and background tasks. Hatchet is an open-source platform for running background tasks and durable workflows at scale.

**Upstream:** [hatchet-dev/hatchet](https://github.com/hatchet-dev/hatchet)

### copilot-cli

GitHub Copilot CLI for interacting with Copilot from your terminal.

**Upstream:** [github/copilot-cli](https://github.com/github/copilot-cli)

### opencode

OpenCode is an open-source AI coding agent that helps you write, edit, and debug code directly from your terminal.

**Upstream:** [anomalyco/opencode](https://github.com/anomalyco/opencode)

**Installation:**

```bash
# Use the pixi CLI to install globally
pixi global install -c https://prefix.dev/longred-forge hatchet-cli copilot-cli opencode

# Or add to a pixi project
pixi add -c https://prefix.dev/longred-forge hatchet-cli copilot-cli opencode

# Using mamba/conda
mamba install -c https://prefix.dev/longred-forge hatchet-cli copilot-cli opencode
miniconda install -c https://prefix.dev/longred-forge hatchet-cli copilot-cli opencode
conda install -c https://prefix.dev/longred-forge hatchet-cli copilot-cli opencode
```

## 🚀 How It Works

1. **Automated Release Tracking**: GitHub Actions runs daily to check for new releases from upstream projects
2. **Recipe Updates**: When a new version is detected, the recipe is automatically updated
3. **Multi-Platform Builds**: Packages are built for Linux (x86_64), macOS (Intel and Apple Silicon), and Windows (x86_64)
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
│   ├── hatchet-cli/
│   │   └── recipe.yaml        # Package recipe
│   ├── copilot-cli/
│   │   └── recipe.yaml        # Package recipe
│   └── opencode/
│       └── recipe.yaml        # Package recipe
├── scripts/
│   ├── build.py                # Local build helper
│   └── update.py               # Release tracking helper
├── .github/
│   └── workflows/
│       └── main.yaml           # CI/CD workflow
├── pixi.toml                   # Dev environment config
└── README.md
```

## 📝 License

This repository is licensed under the MIT License. Individual packages may have their own licenses.

## 🙏 Acknowledgments

- Inspired by [brad-jones/brads-forge](https://github.com/brad-jones/brads-forge)
- Built with [rattler-build](https://github.com/prefix-dev/rattler-build) by [prefix.dev](https://prefix.dev)
- Packages from upstream projects maintain their original licenses and authorship
