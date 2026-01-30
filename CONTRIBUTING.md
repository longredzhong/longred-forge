# Contributing to longred-forge

Thank you for your interest in contributing to longred-forge! This document provides guidelines for contributing to this personal conda package repository.

## How to Contribute

### Suggesting New Packages

If you'd like to suggest a new package to be added to longred-forge:

1. Open an issue with the package name and upstream repository link
2. Explain why this package would be useful
3. Verify the package has a compatible license (open source)
4. Confirm it has regular releases on GitHub

### Reporting Issues

If you encounter issues with existing packages:

1. Check if the issue exists in the upstream project
2. If it's a packaging issue (installation, dependencies, etc.), open an issue here
3. Include:
   - Package name and version
   - Operating system and architecture
   - Installation command used
   - Error messages

### Submitting Changes

For direct contributions:

1. Fork the repository
2. Create a new branch for your changes
3. Make your changes following the guidelines below
4. Test your changes locally
5. Submit a pull request

## Guidelines

### Recipe Guidelines

When creating or updating recipes:

1. **Use the latest version**: Always target the latest stable release
2. **Include checksums**: Use SHA256 checksums for source files (use `skip` for auto-extracted tarballs from GitHub)
3. **Minimal dependencies**: Only include necessary runtime dependencies
4. **Cross-platform**: Support Linux, macOS (Intel and ARM) when possible
5. **Testing**: Include basic tests to verify the package works
6. **Metadata**: Provide accurate homepage, license, and summary

### Workflow Guidelines

When creating or updating workflows:

1. **Use specific versions**: Pin action versions (e.g., `@v4`, not `@latest`)
2. **Security**: Use OIDC authentication when possible
3. **Efficient builds**: Use matrix strategies for multi-platform builds
4. **Error handling**: Include proper error messages and fallbacks
5. **Documentation**: Comment complex workflow steps

### Code Style

- Use 2 spaces for YAML indentation
- Keep lines under 120 characters when possible
- Use descriptive names for jobs and steps
- Comment non-obvious logic

## Testing

### Local Testing

Before submitting a PR, test your changes locally:

```bash
# Install pixi if you haven't
curl -fsSL https://pixi.sh/install.sh | bash

# Build the package
pixi run build --recipe recipes/your-package

# Test the built package
pixi run test --package-file output/*.conda
```

### Manual Installation Test

```bash
# Install locally
mamba install -c local output/*.conda

# Verify it works
your-package --version
```

## Development Setup

### Prerequisites

- [pixi](https://pixi.sh/) - Package management
- [rattler-build](https://rattler-build.prefix.dev/) - Package building
- Git and GitHub account

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/longredzhong/longred-forge.git
cd longred-forge

# Install dependencies
pixi install
```

### Building a Package

```bash
# Build a specific package
pixi run build --recipe recipes/hatchet-cli

# Build for a specific platform
rattler-build build --recipe recipes/hatchet-cli --target-platform linux-64
```

## Release Process

Packages are automatically built and published when:

1. A new version is detected (daily checks)
2. Changes are pushed to the main branch
3. The workflow is manually triggered

The process:
1. GitHub Actions checks for new upstream releases
2. Recipe is updated if a new version is found
3. Packages are built for all platforms
4. Built packages are uploaded to prefix.dev

## Code of Conduct

### Our Standards

- Be respectful and inclusive
- Focus on constructive feedback
- Accept responsibility and learn from mistakes
- Prioritize what's best for the community

### Unacceptable Behavior

- Harassment or discriminatory language
- Trolling or insulting comments
- Publishing others' private information
- Other conduct inappropriate in a professional setting

## Questions?

If you have questions about contributing:

1. Check existing issues and documentation
2. Open a new issue with the "question" label
3. Be specific and provide context

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
