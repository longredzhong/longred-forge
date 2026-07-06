# longred-forge

Personal conda package repository built with [rattler-build](https://github.com/prefix-dev/rattler-build), inspired by [brad-jones/brads-forge](https://github.com/brad-jones/brads-forge).

This repository automatically builds and publishes conda packages to [prefix.dev](https://prefix.dev/channels/longred-forge), making them easily installable via conda/mamba.

## 🚀 Quick Start

To install packages from the `longred-forge` channel, use the following command:

```bash
conda install -c https://prefix.dev/longred-forge <package-name>
mamba install -c https://prefix.dev/longred-forge <package-name>
pixi add -c https://prefix.dev/longred-forge <package-name>
```

**Want to create your own forge?** See the [Configuration Guide](CONFIGURATION.md) to set up your own channel.

## 📦 Available Packages

### hatchet-cli

The Hatchet CLI for managing workflows and background tasks. Hatchet is an open-source platform for running background tasks and durable workflows at scale.

**Upstream:** [hatchet-dev/hatchet](https://github.com/hatchet-dev/hatchet)

### opencode

OpenCode is an open-source AI coding agent that helps you write, edit, and debug code directly from your terminal.

**Upstream:** [anomalyco/opencode](https://github.com/anomalyco/opencode)

### radar

Modern Kubernetes visibility - Local-first, no account, no cloud dependency. Provides topology, event timeline, service traffic, resource browsing, Helm management, and GitOps support.

**Upstream:** [skyhook-io/radar](https://github.com/skyhook-io/radar)

### shaka-packager

A media packaging and development framework for VOD and Live DASH and HLS applications. Supports Common Encryption for Widevine and other DRM systems.

**Upstream:** [shaka-project/shaka-packager](https://github.com/shaka-project/shaka-packager)

### deepseek-tui

DeepSeek TUI is a terminal coding agent for DeepSeek V4. It packages both the `deepseek` dispatcher and the
`deepseek-tui` runtime.

**Upstream:** [Hmbown/DeepSeek-TUI](https://github.com/Hmbown/DeepSeek-TUI)

### claude-code

Claude Code is an agentic coding tool that lives in your terminal, helping you write, edit, and debug code with AI assistance.

**Upstream:** [anthropics/claude-code](https://github.com/anthropics/claude-code)

### garage-webui

A web-based user interface for garage, a lightweight S3-compatible distributed object storage. Provides a graphical dashboard for managing buckets, objects, and storage nodes.

**Upstream:** [khairul169/garage-webui](https://github.com/khairul169/garage-webui)

### mimocode

MiMo-Code is an AI-powered coding agent that helps you write, review, and debug code directly from your terminal.

**Upstream:** [XiaomiMiMo/MiMo-Code](https://github.com/XiaomiMiMo/MiMo-Code)

### obscura

A lightweight Rust headless browser for web scraping and automation. ~70 MB binary, ~30 MB RAM at runtime, with a Chrome DevTools Protocol port that Puppeteer and Playwright connect to unchanged.

**Upstream:** [h4ckf0r0day/obscura](https://github.com/h4ckf0r0day/obscura)

**Installation:**

```bash
# Use the pixi CLI to install globally
pixi global install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager deepseek-tui claude-code garage-webui mimocode obscura

# Or add to a pixi project
pixi add -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager deepseek-tui claude-code garage-webui mimocode obscura

# Using mamba/conda
mamba install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager deepseek-tui claude-code garage-webui mimocode obscura
miniconda install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager deepseek-tui claude-code garage-webui mimocode obscura
conda install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager deepseek-tui claude-code garage-webui mimocode obscura
```

## 🚀 How It Works

1. **Automated Release Tracking**: GitHub Actions runs daily to check for new releases from upstream projects
2. **Recipe Updates**: When a new version is detected, the recipe is automatically updated
3. **Multi-Platform Builds**: Packages are built for Linux (x86_64 and aarch64), macOS (Intel and Apple Silicon), and Windows (x86_64)
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
│   ├── claude-code/
│   │   └── recipe.yaml        # Package recipe
│   ├── deepseek-tui/
│   │   └── recipe.yaml        # Package recipe
│   ├── garage-webui/
│   │   └── recipe.yaml        # Package recipe
│   ├── hatchet-cli/
│   │   └── recipe.yaml        # Package recipe
│   ├── mimocode/
│   │   └── recipe.yaml        # Package recipe
│   ├── obscura/
│   │   └── recipe.yaml        # Package recipe
│   ├── opencode/
│   │   └── recipe.yaml        # Package recipe
│   ├── radar/
│   │   └── recipe.yaml        # Package recipe
│   └── shaka-packager/
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
