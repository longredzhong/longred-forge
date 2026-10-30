import os
import shutil
import stat
import sys

prefix = os.environ.get("PREFIX")
if not prefix:
    exit(1)
bin_dir = (
    os.path.join(prefix, "bin")
    if sys.platform.startswith("linux") or sys.platform == "darwin"
    else os.path.join(prefix, "Scripts")
)
is_unix = sys.platform.startswith("linux") or sys.platform == "darwin"
binaries = (
    ["obscura", "obscura-worker"] if is_unix else ["obscura.exe", "obscura-worker.exe"]
)
os.makedirs(bin_dir, exist_ok=True)
for binary in binaries:
    source = next(
        p
        for p in [binary, f"./{binary}", os.path.join(".", binary)]
        if os.path.isfile(p)
    )
    destination = os.path.join(bin_dir, binary)
    copied = shutil.copy2(source, destination)
    # Preserve the original short-circuit: chmod only runs for a falsy copy result.
    if not copied and is_unix:
        os.chmod(
            destination,
            os.stat(destination).st_mode
            | stat.S_IEXEC
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH,
        )
