"""Install the npm-distributed cf CLI into the conda prefix.

Usage (invoked per-platform by recipe.yaml): install.py <os> <cpu>
  os: linux | darwin | win32      cpu: x64 | arm64

rattler-build strips the npm tarball's single top-level `package/` directory,
so the build directory itself is the package root (package.json sits there
alongside rattler's own script scaffolding, which must not be packaged).

Runs npm install for the *target* platform so cross-builds pick the correct
per-platform optional dependencies (workerd). The package tree and its
command shims are then placed manually: npm's own global bin linking is
host-dependent and cannot be used for cross-builds.
"""
import json
import os
import shutil
import subprocess
import sys

VALID_OS = {"linux", "darwin", "win32"}
VALID_CPU = {"x64", "arm64"}
# --legacy-peer-deps: npm still resolves dev-peer constraints with --omit=dev;
# cf's root msw 3.0.5 conflicts with @cloudflare/workers-auth's msw 2.14.6 peer.
NPM_INSTALL_ARGS = ("install", "--omit=dev", "--ignore-scripts", "--no-audit",
                    "--no-fund", "--legacy-peer-deps", "--loglevel=error")
# rattler-build scaffolding shares the build directory with the unpacked package.
RATTLER_SCAFFOLD = {"conda_build.sh", "conda_build.log", "build_env.sh"}


def fail(message):
    print(f"install.py: {message}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 3:
        fail("expected exactly two arguments: <os> <cpu>")
    os_name, cpu = sys.argv[1], sys.argv[2]
    if os_name not in VALID_OS or cpu not in VALID_CPU:
        fail(f"unexpected platform arguments: {os_name!r} {cpu!r}")
    prefix = os.environ.get("PREFIX")
    if not prefix:
        fail("PREFIX environment variable is not set")

    source_dir = os.getcwd()
    manifest_path = os.path.join(source_dir, "package.json")
    if not os.path.isfile(manifest_path):
        fail("unpacked npm package not found (expected package.json in the build directory)")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    package_name = manifest.get("name")
    bins = manifest.get("bin")
    if not isinstance(package_name, str) or not isinstance(bins, dict) or not bins:
        fail("package manifest lacks a name or bin mapping")

    npm = shutil.which("npm")
    if not npm:
        fail("npm was not found on PATH")
    subprocess.run([npm, *NPM_INSTALL_ARGS, f"--os={os_name}", f"--cpu={cpu}"],
                   cwd=source_dir, check=True)

    if os_name == "win32":
        target_dir = os.path.join(prefix, "node_modules", package_name)
    else:
        target_dir = os.path.join(prefix, "lib", "node_modules", package_name)
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True,
                    ignore=lambda _, names: {name for name in names
                                             if name in RATTLER_SCAFFOLD})
    if not os.path.isdir(os.path.join(target_dir, "node_modules")):
        fail("npm install did not produce node_modules inside the package")

    for name, relative in bins.items():
        if not isinstance(relative, str) or not relative:
            fail(f"unsupported bin entry for {name!r}")
        normalized = relative.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith(("/", "../")):
            fail(f"unsupported bin target for {name!r}: {relative!r}")
        target_file = os.path.join(target_dir, *normalized.split("/"))
        if not os.path.isfile(target_file):
            fail(f"declared bin target is missing: {normalized}")
        if os_name == "win32":
            # Hand-written shims: npm's cmd-shim paths are relative and must not
            # be relocated, so they are authored directly against %~dp0.
            scripts_dir = os.path.join(prefix, "Scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            backslash = normalized.replace("/", "\\")
            shim = os.path.join(scripts_dir, f"{name}.cmd")
            with open(shim, "w", encoding="ascii", newline="") as handle:
                handle.write("@ECHO off\r\n")
                handle.write(f'node "%~dp0..\\node_modules\\{package_name}\\{backslash}" %*\r\n')
        else:
            bin_dir = os.path.join(prefix, "bin")
            os.makedirs(bin_dir, exist_ok=True)
            dest = os.path.join(bin_dir, name)
            # cf's npm bin script imports ../dist/delegate.mjs relative to its own
            # location. Copying it into prefix/bin breaks that import, so install a
            # relocatable shim that executes the script inside the package tree.
            relative_target = os.path.relpath(target_file, bin_dir).replace(os.sep, "/")
            with open(dest, "w", encoding="ascii", newline="\n") as handle:
                handle.write("#!/bin/sh\n")
                handle.write(f'exec node "$(dirname "$0")/{relative_target}" "$@"\n')
            os.chmod(dest, os.stat(dest).st_mode
                     | stat.S_IEXEC | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    main()
