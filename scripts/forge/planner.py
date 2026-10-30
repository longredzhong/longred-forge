"""Let rattler-build resolve selectors and exact package identities."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

PLATFORMS = ('linux-64', 'linux-aarch64', 'osx-64', 'osx-arm64', 'win-64')


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    build: str
    platform: str

    @property
    def filename(self) -> str:
        return f'{self.name}-{self.version}-{self.build}.conda'

    def path(self, output: Path) -> Path:
        return output / self.platform / self.filename


def render(recipe: Path, target: str) -> list[Artifact]:
    result = subprocess.run(
        ['rattler-build', 'build', '-r', str(recipe), '--target-platform', target, '--render-only'],
        check=True, capture_output=True, text=True, encoding='utf-8',
    )
    artifacts = []
    for item in json.loads(result.stdout):
        doc = item['recipe']
        package = doc['package']
        artifacts.append(Artifact(
            package['name'], str(package['version']), doc['build']['string'],
            item['build_configuration']['target_platform'],
        ))
    return artifacts


def changed_recipes(base: str, head: str = 'HEAD') -> list[Path]:
    result = subprocess.run(
        ['git', 'diff', '--name-only', base, head], check=True, capture_output=True, text=True,
    )
    paths = [Path(line) for line in result.stdout.splitlines()]
    if any(p.parts[0] in ('scripts', 'tests', '.github') or p.name in ('pixi.toml', 'pixi.lock') for p in paths):
        return sorted(Path('recipes').glob('*/recipe.yaml'))
    names = {p.parts[1] for p in paths if len(p.parts) >= 3 and p.parts[0] == 'recipes'}
    return sorted(p for name in names if (p := Path('recipes') / name / 'recipe.yaml').is_file())
