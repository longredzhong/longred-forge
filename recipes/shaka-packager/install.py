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
binary_name = (
    "packager"
    if sys.platform.startswith("linux") or sys.platform == "darwin"
    else "packager.exe"
)
os.makedirs(bin_dir, exist_ok=True)
source_patterns = [
    binary_name,
    f"packager-linux-x64",
    f"packager-linux-arm64",
    f"packager-osx-x64",
    f"packager-osx-arm64",
    f"packager-win-x64.exe",
    f"./{binary_name}",
    os.path.join(".", binary_name),
]
source_file = next((p for p in source_patterns if os.path.isfile(p)), None)
if not source_file:
    exit(1)
dest_file = os.path.join(bin_dir, binary_name)
shutil.copy2(source_file, dest_file)
if sys.platform.startswith("linux") or sys.platform == "darwin":
    os.chmod(
        dest_file,
        os.stat(dest_file).st_mode
        | stat.S_IEXEC
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH,
    )
