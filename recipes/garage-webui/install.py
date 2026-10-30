import os
import shutil
import stat
import sys
import glob

prefix = os.environ.get("PREFIX")
if not prefix:
    exit(1)
bin_dir = os.path.join(prefix, "bin")
os.makedirs(bin_dir, exist_ok=True)
source_files = glob.glob("garage-webui-v*")
if not source_files:
    exit(1)
source_file = source_files[0]
dest_file = os.path.join(bin_dir, "garage-webui")
shutil.copy2(source_file, dest_file)
os.chmod(
    dest_file,
    os.stat(dest_file).st_mode
    | stat.S_IEXEC
    | stat.S_IXUSR
    | stat.S_IXGRP
    | stat.S_IXOTH,
)
