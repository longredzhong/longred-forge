import glob
import gzip
import os
import shutil
import sys

prefix = os.environ["PREFIX"]
is_unix = not sys.platform.startswith("win")
bin_dir = os.path.join(prefix, "bin" if is_unix else "Scripts")
os.makedirs(bin_dir, exist_ok=True)
dest = os.path.join(bin_dir, "mihomo" if is_unix else "mihomo.exe")
src = None if is_unix else glob.glob("**/*.exe", recursive=True)[0]
if is_unix:
    open(dest, "wb").write(gzip.decompress(open("mihomo.gz", "rb").read()))
else:
    shutil.copy2(src, dest)
if is_unix:
    os.chmod(dest, os.stat(dest).st_mode | 493)
