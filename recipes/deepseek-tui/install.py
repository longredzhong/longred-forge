import os
import shutil
import stat
import sys

prefix = os.environ.get("PREFIX")
if not prefix:
    print("Error: PREFIX is not set", file=sys.stderr)
    sys.exit(1)
is_unix = sys.platform.startswith("linux") or sys.platform == "darwin"
bin_dir = os.path.join(prefix, "bin") if is_unix else os.path.join(prefix, "Scripts")
os.makedirs(bin_dir, exist_ok=True)
binaries = [
    ("codewhale-linux-x64", "codewhale"),
    ("codewhale-linux-arm64", "codewhale"),
    ("codewhale-macos-x64", "codewhale"),
    ("codewhale-macos-arm64", "codewhale"),
    ("codewhale-windows-x64.exe", "codewhale.exe"),
    ("codewhale-tui-linux-x64", "codewhale-tui"),
    ("codewhale-tui-linux-arm64", "codewhale-tui"),
    ("codewhale-tui-macos-x64", "codewhale-tui"),
    ("codewhale-tui-macos-arm64", "codewhale-tui"),
    ("codewhale-tui-windows-x64.exe", "codewhale-tui.exe"),
]
selected = [(src, dst) for src, dst in binaries if os.path.isfile(src)]
if len(selected) != 2:
    print(f"Error: expected exactly 2 binaries, found {len(selected)}", file=sys.stderr)
    sys.exit(1)
for src, dst in selected:
    dest = os.path.join(bin_dir, dst)
    shutil.copy2(src, dest)
    if is_unix:
        os.chmod(
            dest,
            os.stat(dest).st_mode
            | stat.S_IEXEC
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH,
        )
