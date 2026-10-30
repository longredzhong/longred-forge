import os
import shutil
import stat
import sys

prefix = os.environ.get("PREFIX")
if not prefix:
    exit(1)
bin_dir = os.path.join(prefix, "bin")
binary_name = "sofka"
os.makedirs(bin_dir, exist_ok=True)
source_patterns = [binary_name, f"./{binary_name}", os.path.join(".", binary_name)]
source_file = next((p for p in source_patterns if os.path.isfile(p)), None)
if not source_file:
    exit(1)
dest_file = os.path.join(bin_dir, binary_name)
shutil.copy2(source_file, dest_file)
os.chmod(
    dest_file,
    os.stat(dest_file).st_mode
    | stat.S_IEXEC
    | stat.S_IXUSR
    | stat.S_IXGRP
    | stat.S_IXOTH,
)
