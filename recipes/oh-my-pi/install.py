import os
import shutil
from pathlib import Path

windows = os.name == 'nt'
prefix = Path(os.environ['PREFIX'])
bin_dir = prefix / ('Scripts' if windows else 'bin')
bin_dir.mkdir(parents=True, exist_ok=True)
candidates = [p for p in Path('.').glob('omp-*') if p.is_file()]
if len(candidates) != 1:
    raise RuntimeError(f'Expected one OMP executable, found {candidates}')
destination = bin_dir / ('omp.exe' if windows else 'omp')
shutil.copy2(candidates[0], destination)
if not windows:
    destination.chmod(destination.stat().st_mode | 0o111)
