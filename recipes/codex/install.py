import os
import shutil
from pathlib import Path

prefix = Path(os.environ['PREFIX'])
windows = os.name == 'nt'
bin_dir = prefix / ('Scripts' if windows else 'bin')
bin_dir.mkdir(parents=True, exist_ok=True)
suffix = '.exe' if windows else ''
candidates = [p for p in Path('.').rglob('codex-*' + suffix) if p.is_file() and (windows or '.' not in p.name)]
if len(candidates) != 1:
    raise RuntimeError(f'Expected one Codex executable, found {candidates}')
destination = bin_dir / ('codex' + suffix)
shutil.copy2(candidates[0], destination)
if not windows:
    destination.chmod(destination.stat().st_mode | 0o111)
