"""Install the npm-distributed @deepseek-ai/dsh CLI into the conda prefix.

Usage (invoked per-platform by recipe.yaml): install.py <os> <cpu>
  os: linux | darwin | win32      cpu: x64 | arm64

rattler-build strips the npm tarball's single top-level `package/` directory,
so the build directory itself is the package root (package.json sits there
alongside rattler's own script scaffolding, which must not be packaged).

Runs npm install for the *target* platform so cross-builds pick the correct
per-platform optional dependencies. Command shims are placed manually because
npm's global bin linking is host-dependent and relative ESM imports inside
lib/bin.js require executing from inside the installed package tree.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

VALID_OS = {"linux", "darwin", "win32"}
VALID_CPU = {"x64", "arm64"}
NPM_INSTALL_ARGS = (
    "install",
    "--omit=dev",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    "--loglevel=error",
)
# rattler-build scaffolding shares the build directory with the unpacked package.
RATTLER_SCAFFOLD = {
    "conda_build.sh",
    "conda_build.bat",
    "conda_build.log",
    "build_env.sh",
    "build_env.bat",
}


def fail(message):
    """Print an error message to stderr and exit nonzero."""
    print(f"install.py: {message}", file=sys.stderr)
    sys.exit(1)


def parse_target_args(argv):
    """Validate and return the target (os_name, cpu) pair from CLI arguments."""
    if len(argv) != 3:
        fail("expected exactly two arguments: <os> <cpu>")
    os_name, cpu = argv[1], argv[2]
    if os_name not in VALID_OS or cpu not in VALID_CPU:
        fail(f"unexpected platform arguments: {os_name!r} {cpu!r}")
    return os_name, cpu


def load_manifest(source_dir):
    """Load package.json and return validated (package_parts, bins_mapping)."""
    manifest_path = os.path.join(source_dir, "package.json")
    if not os.path.isfile(manifest_path):
        fail("unpacked npm package not found (expected package.json in the build directory)")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    package_name = manifest.get("name")
    if not isinstance(package_name, str) or not package_name.strip():
        fail("package manifest lacks a valid name")
    package_parts = [part for part in package_name.strip().split("/") if part]
    if not package_parts or any(part in {".", ".."} for part in package_parts):
        fail(f"unsupported package name: {package_name!r}")

    bins = manifest.get("bin")
    if isinstance(bins, str) and bins.strip():
        bins = {package_parts[-1]: bins}
    if not isinstance(bins, dict) or not bins:
        fail("package manifest lacks a bin mapping")
    return package_parts, bins


def install_dependencies(source_dir, os_name, cpu):
    """Run npm install for the target os/cpu without lifecycle scripts."""
    npm = shutil.which("npm")
    if not npm:
        fail("npm was not found on PATH")
    subprocess.run(
        [npm, *NPM_INSTALL_ARGS, f"--os={os_name}", f"--cpu={cpu}"],
        cwd=source_dir,
        check=True,
    )


def copy_package_tree(source_dir, target_dir):
    """Copy unpacked package and node_modules into the prefix, excluding scaffold files."""
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    shutil.copytree(
        source_dir,
        target_dir,
        dirs_exist_ok=True,
        ignore=lambda _, names: {name for name in names if name in RATTLER_SCAFFOLD},
    )
    if not os.path.isdir(os.path.join(target_dir, "node_modules")):
        fail("npm install did not produce node_modules inside the package")


def write_bin_shim(os_name, prefix, package_parts, name, relative, target_dir):
    """Create a relocatable wrapper script pointing into the installed package tree."""
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        fail(f"unsupported bin command name: {name!r}")
    if not isinstance(relative, str) or not relative:
        fail(f"unsupported bin entry for {name!r}")
    normalized = relative.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith(("/", "../")):
        fail(f"unsupported bin target for {name!r}: {relative!r}")

    target_root = Path(target_dir).resolve()
    target_path = (target_root / Path(*normalized.split("/"))).resolve()
    if not target_path.is_relative_to(target_root) or not target_path.is_file():
        fail(f"declared bin target is missing or escapes package root: {normalized}")
    rel_inside_pkg = target_path.relative_to(target_root).as_posix()

    if os_name == "win32":
        scripts_dir = os.path.join(prefix, "Scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        package_subpath = "\\".join(package_parts)
        backslash = rel_inside_pkg.replace("/", "\\")
        shim = os.path.join(scripts_dir, f"{name}.cmd")
        with open(shim, "w", encoding="ascii", newline="") as handle:
            handle.write("@ECHO off\r\n")
            handle.write(
                f'node "%~dp0..\\node_modules\\{package_subpath}\\{backslash}" %*\r\n'
            )
        return

    bin_dir = os.path.join(prefix, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    dest = os.path.join(bin_dir, name)
    relative_target = os.path.relpath(
        os.path.join(target_dir, *rel_inside_pkg.split("/")), bin_dir
    ).replace(os.sep, "/")
    with open(dest, "w", encoding="ascii", newline="\n") as handle:
        handle.write("#!/bin/sh\n")
        handle.write(f'exec node "$(dirname "$0")/{relative_target}" "$@"\n')
    os.chmod(dest, 0o755)


def main():
    """Install @deepseek-ai/dsh and its relocatable command shims into PREFIX."""
    os_name, cpu = parse_target_args(sys.argv)
    prefix = os.environ.get("PREFIX")
    if not prefix:
        fail("PREFIX environment variable is not set")

    source_dir = os.getcwd()
    package_parts, bins = load_manifest(source_dir)
    install_dependencies(source_dir, os_name, cpu)

    if os_name == "win32":
        target_dir = os.path.join(prefix, "node_modules", *package_parts)
    else:
        target_dir = os.path.join(prefix, "lib", "node_modules", *package_parts)
    copy_package_tree(source_dir, target_dir)

    for name, relative in bins.items():
        write_bin_shim(os_name, prefix, package_parts, name, relative, target_dir)


if __name__ == "__main__":
    main()
