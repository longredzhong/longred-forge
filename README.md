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

### opencode2

OpenCode second generation, maintained separately from the incompatible v1 line. Install the `opencode2` package and run `opencode2`; the existing `opencode` package and command remain on v1. Both packages can coexist without overwriting executable files. This does not guarantee compatible configuration, plugins, or session data; use separate environments and back up existing data before migration.

```bash
pixi global install -c https://prefix.dev/longred-forge opencode2
opencode2 --version
```

**Upstream:** [anomalyco/opencode](https://github.com/anomalyco/opencode)

### radar

Modern Kubernetes visibility - Local-first, no account, no cloud dependency. Provides topology, event timeline, service traffic, resource browsing, Helm management, and GitOps support.

**Upstream:** [skyhook-io/radar](https://github.com/skyhook-io/radar)

### shaka-packager

A media packaging and development framework for VOD and Live DASH and HLS applications. Supports Common Encryption for Widevine and other DRM systems.

**Upstream:** [shaka-project/shaka-packager](https://github.com/shaka-project/shaka-packager)

### codex

OpenAI Codex CLI, installed as `codex`.

**Upstream:** [openai/codex](https://github.com/openai/codex)

### oh-my-pi

Oh My Pi coding agent, installed as `omp`. Maintained separately from the `pi` package.

**Upstream:** [can1357/oh-my-pi](https://github.com/can1357/oh-my-pi)

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

### pi

Pi is an open-source AI coding agent that lives in your terminal. It helps you write, edit, and debug code through natural language commands, providing intelligent code assistance.

**Upstream:** [earendil-works/pi](https://github.com/earendil-works/pi)

### sofka

A Kubernetes TUI, reimagined in Rust - built on kube-rs and ratatui, async-first from the ground up.

**Upstream:** [nklmilojevic/sofka](https://github.com/nklmilojevic/sofka)

### mihomo

Mihomo (formerly Clash.Meta) is a rule-based tunnel written in Go. It supports a wide range of proxy
protocols, rule-based routing with GEOIP/GEOSITE databases, a RESTful external controller, transparent
proxy, TUN mode and DNS-based traffic splitting.

**Upstream:** [MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo)

> The amd64 builds are upstream's `compatible` variants (GOAMD64=v1), so they run on every x86-64 CPU
> instead of requiring AVX2.

**Installation:**

```bash
# Use the pixi CLI to install globally
pixi global install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager codex oh-my-pi claude-code garage-webui mimocode obscura pi sofka mihomo

# Or add to a pixi project
pixi add -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager codex oh-my-pi claude-code garage-webui mimocode obscura pi sofka mihomo

# Using mamba/conda
mamba install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager codex oh-my-pi claude-code garage-webui mimocode obscura pi sofka mihomo
conda install -c https://prefix.dev/longred-forge hatchet-cli opencode radar shaka-packager codex oh-my-pi claude-code garage-webui mimocode obscura pi sofka mihomo
```

## 🚀 How It Works

1. **Automated Release Tracking**: GitHub Actions runs every three hours (at minute 10) to check for new releases from upstream projects
2. **Recipe Updates**: When a new version is detected, the recipe is automatically updated
3. **Multi-Platform Builds**: The build matrix covers Linux (x86_64 and aarch64), macOS (Intel and Apple Silicon), and Windows (x86_64); individual recipes skip unsupported targets.
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
│   ├── codex/
│   │   └── recipe.yaml        # Package recipe
│   ├── garage-webui/
│   │   └── recipe.yaml        # Package recipe
│   ├── hatchet-cli/
│   │   └── recipe.yaml        # Package recipe
│   ├── mihomo/
│   │   └── recipe.yaml        # Package recipe
│   ├── mimocode/
│   │   └── recipe.yaml        # Package recipe
│   ├── obscura/
│   │   └── recipe.yaml        # Package recipe
│   ├── oh-my-pi/
│   │   ├── install.py
│   │   └── recipe.yaml
│   ├── opencode/
│   │   └── recipe.yaml        # Package recipe
│   ├── pi/
│   │   └── recipe.yaml        # Package recipe
│   ├── radar/
│   │   └── recipe.yaml        # Package recipe
│   ├── shaka-packager/
│   │   └── recipe.yaml        # Package recipe
│   └── sofka/
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

## Local Development

```bash
pixi install
pixi run test
pixi run validate
pixi run lint
pixi run build --recipe-path recipes/garage-webui/recipe.yaml --no-upload
pixi run update --dry-run
```

The `build` task runs `python scripts/build.py`. Builds use the original recipe directory so each
recipe can invoke its adjacent `install.py`. Python is a build dependency, not a new runtime dependency.
On Unix, scripts use `python "$RECIPE_DIR/install.py"`; on Windows, they use
`python "%RECIPE_DIR%/install.py"`, matching rattler-build's bash/cmd environment syntax.

Package availability depends on upstream assets and recipe `build.skip` conditions; the matrix does
not guarantee that every package is available on every platform. Publishing requires a channel-write
API token (`PREFIX_TOKEN`, or locally `PREFIX_API_KEY`); use `--no-upload` for local validation.

## 📝 License

This repository is licensed under the MIT License. Individual packages may have their own licenses.

## 🙏 Acknowledgments

- Inspired by [brad-jones/brads-forge](https://github.com/brad-jones/brads-forge)
- Built with [rattler-build](https://github.com/prefix-dev/rattler-build) by [prefix.dev](https://prefix.dev)
- Packages from upstream projects maintain their original licenses and authorship

## Retired packages

`deepseek-tui` (CodeWhale) is no longer built, updated, or recommended by this repository. Previously published artifacts are retained for reproducibility; existing installations are not automatically removed. Codex (`codex`) and Oh My Pi (`omp`) are independent alternatives, not drop-in migrations of CodeWhale data.
