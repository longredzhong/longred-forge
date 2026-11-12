#!/usr/bin/env python3
"""Install published skill packages with Pixi and expose them to project agents."""
import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import httpx

CHANNEL = 'https://prefix.dev/longredzhong/longred-skills-forge'


class AgentPath:
    def __init__(self, local: str, global_path: str):
        self.local = local
        self.global_path = global_path


CANONICAL_AGENTS = {
    'agents': AgentPath('.agents/skills', '.agents/skills'),
    'claude': AgentPath('.claude/skills', '.claude/skills'),
    'cursor': AgentPath('.cursor/skills', '.cursor/skills'),
    'windsurf': AgentPath('.windsurf/skills', '.codeium/windsurf/skills'),
    'copilot': AgentPath('.github/skills', '.github/skills'),
}

# Agents that conform to the standard .agents/skills specification alias to 'agents'
AGENT_ALIASES = {
    'codex': 'agents',
    'cline': 'agents',
    'gemini': 'agents',
    'opencode': 'agents',
}

# Backward compatibility map
AGENTS = {name: path.local for name, path in CANONICAL_AGENTS.items()}

NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def get_agent_dir(target_root: Path, agent_name: str, is_global: bool = False) -> Path:
    """Resolve the directory path for an agent based on local or global scope."""
    canonical = AGENT_ALIASES.get(agent_name, agent_name)
    if canonical not in CANONICAL_AGENTS:
        raise ValueError(f"Unknown agent: '{agent_name}'")
    agent_path = CANONICAL_AGENTS[canonical]
    subpath = agent_path.global_path if is_global else agent_path.local
    return target_root / subpath


def project_root(start: Path) -> Path:
    """Find the nearest Pixi workspace, including workspaces in pyproject.toml."""
    for directory in (start, *start.parents):
        if (directory / 'pixi.toml').is_file():
            return directory
        manifest = directory / 'pyproject.toml'
        if manifest.is_file():
            try:
                with manifest.open('rb') as f:
                    data = tomllib.load(f)
                if 'pixi' in data.get('tool', {}):
                    return directory
            except Exception:
                pass
    return start


def read_config(root: Path) -> dict:
    """Read project-level longred-skills configuration from pixi.toml or pyproject.toml."""
    for manifest_name in ('pixi.toml', 'pyproject.toml'):
        manifest = root / manifest_name
        if manifest.is_file():
            try:
                with manifest.open('rb') as f:
                    data = tomllib.load(f)
                cfg = data.get('tool', {}).get('longred-skills')
                if isinstance(cfg, dict):
                    return cfg
                meta = data.get('workspace', {}).get('metadata', {}).get('longred-skills')
                if isinstance(meta, dict):
                    return meta
            except Exception:
                pass
    return {}


def global_workspace_root(environment: str) -> tuple[Path, Path]:
    """Determine global target root (home) and workspace root following XDG / OS conventions."""
    target_root = Path.home()
    xdg = os.environ.get('XDG_DATA_HOME')
    real_home = Path(os.path.expanduser('~'))
    if xdg and target_root == real_home:
        base = Path(xdg)
    else:
        base = target_root / '.local' / 'share'
    workspace_root = base / 'longred-skills' / environment
    return target_root, workspace_root


def resolve_agents(agent_arg: str | list[str] | None, default_agents: list[str] | None = None) -> list[str]:
    """Resolve agent argument into a deduplicated list of canonical agent names."""
    if not agent_arg:
        if default_agents:
            return resolve_agents(default_agents)
        return ['agents']
    if isinstance(agent_arg, list):
        items = agent_arg
    elif agent_arg == 'all':
        return list(CANONICAL_AGENTS.keys())
    else:
        items = [a.strip() for a in agent_arg.split(',') if a.strip()]

    selected = []
    valid = sorted(list(CANONICAL_AGENTS.keys()) + list(AGENT_ALIASES.keys()) + ['all'])
    for agent in items:
        canonical = AGENT_ALIASES.get(agent, agent)
        if canonical not in CANONICAL_AGENTS:
            raise ValueError(f"Unknown agent: '{agent}'. Valid choices: {', '.join(valid)}")
        if canonical not in selected:
            selected.append(canonical)
    return selected or ['agents']


def prune_dangling(target_root, root, environment, agents):
    """Safely prune symlinks in agent directories that point to deleted or stale skills in this Pixi environment."""
    source = root / '.pixi' / 'envs' / environment / 'share' / 'agent-skills'
    valid_skills = set()
    if source.is_dir():
        valid_skills = {p.name for p in source.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file()}
    pruned = []
    is_global = target_root is not None
    effective_target_root = target_root or root
    for agent in agents:
        target = get_agent_dir(effective_target_root, agent, is_global=is_global)
        if not target.is_dir():
            continue
        for item in list(target.iterdir()):
            if not item.is_symlink():
                continue
            try:
                raw_target = os.readlink(item)
            except OSError:
                continue

            norm_dest = Path(os.path.normpath(item.parent / raw_target))
            is_under_source = False
            try:
                norm_dest.relative_to(source)
                is_under_source = True
            except ValueError:
                try:
                    item.resolve().relative_to(source.resolve())
                    is_under_source = True
                except (ValueError, OSError):
                    pass

            if is_under_source and (not norm_dest.exists() or item.name not in valid_skills):
                item.unlink()
                pruned.append((agent, item.name))
                print(f'pruned: {item} (target removed)')
    return pruned


def plan_sync(root, environment, agent, selected=None, allow_empty=False, target_root=None):
    """Check all destinations before any filesystem or Pixi changes."""
    if not NAME.fullmatch(environment):
        raise ValueError('Invalid environment name')
    is_global = target_root is not None
    target = get_agent_dir(target_root or root, agent, is_global=is_global)
    if (target.parent.exists() or target.parent.is_symlink()) and not target.parent.is_dir():
        raise FileExistsError(f'Agent configuration directory conflicts: {target.parent}')
    if (target.exists() or target.is_symlink()) and not target.is_dir():
        raise FileExistsError(f'Agent skill directory conflicts: {target}')
    source = root / '.pixi' / 'envs' / environment / 'share' / 'agent-skills'
    if not source.is_dir():
        if allow_empty:
            return [], []
        raise ValueError(f'No installed skills found in {source}')
    skills = sorted(p for p in source.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file())
    if selected:
        skills = [p for p in skills if p.name == selected]
        if not skills:
            raise ValueError(f'Skill not found in environment: {selected}')
    if not skills:
        if allow_empty:
            return [], []
        raise ValueError('No installed skills found')
    actions = []
    for skill in skills:
        if not NAME.fullmatch(skill.name):
            raise ValueError(f'Invalid skill name: {skill.name}')
        dest = target / skill.name
        if dest.is_symlink():
            if dest.resolve() != skill.resolve():
                raise FileExistsError(f'Existing symlink conflicts: {dest}')
        elif dest.exists():
            raise FileExistsError(f'Existing path conflicts: {dest}')
        else:
            actions.append((skill, dest))
    return skills, actions


def sync(root, environment, agent_choice, selected=None, target_root=None, prune=True):
    """Synchronize installed skills to one or more agent directories."""
    agents = resolve_agents(agent_choice)
    effective_target_root = target_root or root
    is_global = target_root is not None
    for agent in agents:
        skills, actions = plan_sync(root, environment, agent, selected, target_root=target_root)
        target = get_agent_dir(effective_target_root, agent, is_global=is_global)
        target.mkdir(parents=True, exist_ok=True)
        for skill, dest in actions:
            try:
                dest.symlink_to(os.path.relpath(skill, dest.parent), target_is_directory=True)
                print(f'linked: {dest} -> {skill}')
            except OSError as exc:
                if sys.platform == 'win32' and getattr(exc, 'winerror', None) == 1314:
                    raise OSError(
                        f'Failed to create symlink {dest}: Windows requires Developer Mode '
                        'or administrator privileges to create directory symlinks. '
                        'Please enable Developer Mode in Windows Settings.'
                    ) from exc
                raise
        print(f'{len(skills)} skill(s) available for {agent}')

    if prune and not selected:
        prune_dangling(effective_target_root, root, environment, agents)


def clean(root: Path, environment: str, agent_choice: str | None, all_envs: bool = False, target_root: Path | None = None):
    """Safely remove managed symlinks pointing to this Pixi environment (or all Pixi environments)."""
    agents = resolve_agents(agent_choice)
    effective_target_root = target_root or root
    is_global = target_root is not None
    envs_dir = root / '.pixi' / 'envs'

    cleaned = []
    for agent in agents:
        target = get_agent_dir(effective_target_root, agent, is_global=is_global)
        if not target.is_dir():
            continue
        for item in list(target.iterdir()):
            if not item.is_symlink():
                continue
            try:
                raw_target = os.readlink(item)
            except OSError:
                continue
            norm_dest = Path(os.path.normpath(item.parent / raw_target))

            should_clean = False
            if all_envs:
                try:
                    norm_dest.relative_to(envs_dir)
                    should_clean = True
                except ValueError:
                    try:
                        item.resolve().relative_to(envs_dir.resolve())
                        should_clean = True
                    except (ValueError, OSError):
                        pass
            else:
                source = envs_dir / environment / 'share' / 'agent-skills'
                try:
                    norm_dest.relative_to(source)
                    should_clean = True
                except ValueError:
                    try:
                        item.resolve().relative_to(source.resolve())
                        should_clean = True
                    except (ValueError, OSError):
                        pass

            if should_clean:
                item.unlink()
                cleaned.append((agent, item.name))
                print(f'cleaned: {item}')
    print(f'Cleaned {len(cleaned)} skill link(s)')
    return cleaned


def switch_environment(root: Path, target_env: str, agent_choice: str | None, target_root: Path | None = None):
    """Switch active skill links to target_env by cleaning old environment links and syncing target_env."""
    if not NAME.fullmatch(target_env):
        raise ValueError('Invalid environment name')
    print(f'Switching skills to environment: {target_env}')
    clean(root, target_env, agent_choice, all_envs=True, target_root=target_root)
    sync(root, target_env, agent_choice, target_root=target_root, prune=True)


def manage_interactive(root: Path, environment: str, agent_choice: str | None, target_root: Path | None = None):
    """Interactive TUI to select and toggle skills for target agent."""
    agents = resolve_agents(agent_choice)
    agent = agents[0]  # manage primary agent
    effective_target_root = target_root or root
    is_global = target_root is not None
    source = root / '.pixi' / 'envs' / environment / 'share' / 'agent-skills'
    if not source.is_dir():
        print(f'No installed skills found in {source}')
        return

    available_skills = sorted(p for p in source.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file())
    if not available_skills:
        print('No installed skills found')
        return

    target = get_agent_dir(effective_target_root, agent, is_global=is_global)
    target.mkdir(parents=True, exist_ok=True)

    skills_meta = []
    for skill in available_skills:
        dest = target / skill.name
        is_linked = False
        try:
            if dest.is_symlink() and (dest.samefile(skill) or dest.resolve() == skill.resolve()):
                is_linked = True
        except OSError:
            pass
        desc = ''
        content = (skill / 'SKILL.md').read_text(encoding='utf-8', errors='replace')
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if line.startswith('description:'):
                        desc = line.split(':', 1)[1].strip().strip('\'"')
                        break
        skills_meta.append((skill, is_linked, desc))

    selected_names = set()
    use_questionary = False
    try:
        import questionary
        if sys.stdin.isatty():
            use_questionary = True
    except ImportError:
        pass

    if use_questionary:
        choices = []
        for skill, is_linked, desc in skills_meta:
            title = f"{skill.name}" + (f" ({desc[:60]}...)" if len(desc) > 60 else f" ({desc})" if desc else "")
            choices.append(questionary.Choice(title=title, value=skill.name, checked=is_linked))
        answer = questionary.checkbox(
            f"Select skills to enable for '{agent}' ({target}):",
            choices=choices,
            instruction="(space: toggle, enter: confirm, a: toggle all)"
        ).ask()
        if answer is None:
            print("Cancelled.")
            return
        selected_names = set(answer)
    else:
        print(f"\nManaging skills for '{agent}' in {target}:")
        current_state = {skill.name: is_linked for skill, is_linked, _ in skills_meta}
        if not sys.stdin.isatty():
            return
        for idx, (skill, is_linked, desc) in enumerate(skills_meta, 1):
            mark = '[x]' if is_linked else '[ ]'
            d_str = f" - {desc[:50]}..." if desc else ""
            print(f"  [{idx}] {mark} {skill.name}{d_str}")
        print("\nEnter skill numbers to toggle (e.g. '1, 2'), 'all', 'none', or 'c' to save/continue:")
        while True:
            try:
                line = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if line in ('c', 'save', 'exit', 'q', ''):
                break
            if line == 'all':
                for k in current_state:
                    current_state[k] = True
            elif line == 'none':
                for k in current_state:
                    current_state[k] = False
            else:
                for part in line.split(','):
                    part = part.strip()
                    if part.isdigit():
                        idx = int(part)
                        if 1 <= idx <= len(skills_meta):
                            name = skills_meta[idx - 1][0].name
                            current_state[name] = not current_state[name]
            for idx, (skill, _, desc) in enumerate(skills_meta, 1):
                mark = '[x]' if current_state[skill.name] else '[ ]'
                print(f"  [{idx}] {mark} {skill.name}")
            print("Toggle more or enter 'c' to save:")
        selected_names = {k for k, v in current_state.items() if v}

    to_link = [skill for skill, is_linked, _ in skills_meta if skill.name in selected_names and not is_linked]
    to_unlink = [skill for skill, is_linked, _ in skills_meta if skill.name not in selected_names and is_linked]
    for skill in to_link:
        dest = target / skill.name
        if dest.is_symlink():
            dest.unlink()
        dest.symlink_to(os.path.relpath(skill, dest.parent), target_is_directory=True)
        print(f'linked: {dest} -> {skill}')
    for skill in to_unlink:
        dest = target / skill.name
        if dest.is_symlink():
            dest.unlink()
            print(f'unlinked: {dest}')
    print(f"Updated skills for '{agent}': {len(selected_names)} enabled")


def fetch_repodata():
    """Fetch remote repository metadata from the published channel."""
    with httpx.Client(trust_env=False, follow_redirects=True, timeout=30) as client:
        response = client.get(CHANNEL + '/noarch/repodata.json')
        response.raise_for_status()
        return response.json()


def resolve_package_name(input_name: str, repodata=None) -> str:
    """Resolve friendly names (e.g. 'find-skills') to canonical 'agent-skill-*' package names."""
    if NAME.fullmatch(input_name) and input_name.startswith('agent-skill-'):
        return input_name
    if repodata is None:
        try:
            repodata = fetch_repodata()
        except Exception:
            repodata = {}
    packages = repodata.get('packages.conda', {}) | repodata.get('packages', {})
    known_names = {p['name'] for p in packages.values() if p['name'].startswith('agent-skill-')}

    candidate = f'agent-skill-{input_name}'
    if candidate in known_names:
        return candidate

    suffix = f'-{input_name}'
    matches = sorted({name for name in known_names if name.endswith(suffix)})
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous skill name '{input_name}'. Matching packages: {', '.join(matches)}")

    substring_matches = sorted({name for name in known_names if input_name.lower() in name.lower()})
    if len(substring_matches) == 1:
        return substring_matches[0]
    if len(substring_matches) > 1:
        raise ValueError(f"Ambiguous skill name '{input_name}'. Matching packages: {', '.join(substring_matches)}")

    raise ValueError(f"Expected an agent-skill-* package name or known skill name, got '{input_name}'")


def find_skills(query: str):
    """Search published skills by package name and description/summary."""
    data = fetch_repodata()
    packages = data.get('packages.conda', {}) | data.get('packages', {})
    q = query.lower()
    matches = {}
    for p in packages.values():
        name = p.get('name', '')
        if not name.startswith('agent-skill-'):
            continue
        summary = p.get('summary', '') or p.get('about', {}).get('summary', '')
        if not q or q in name.lower() or q in summary.lower():
            version = p.get('version', '')
            matches[name] = (version, summary)

    if not matches:
        print('No matching skills')
        return

    max_len = max(len(name) for name in matches)
    for name in sorted(matches):
        version, summary = matches[name]
        ver_str = f'v{version}' if version else ''
        if summary:
            print(f'{name:<{max_len}}  {ver_str:<8}  {summary}')
        else:
            print(f'{name:<{max_len}}  {ver_str}')


def show_info(name: str, root: Path, environment: str, target_root: Path | None):
    """Show detailed metadata and agent link status for an installed skill or channel package."""
    effective_target_root = target_root or root
    is_global = target_root is not None
    source = root / '.pixi' / 'envs' / environment / 'share' / 'agent-skills'
    skill_dir = None
    if source.is_dir():
        cand = source / name
        if cand.is_dir() and (cand / 'SKILL.md').is_file():
            skill_dir = cand
        else:
            for p in source.iterdir():
                if p.is_dir() and (p / 'SKILL.md').is_file():
                    if p.name == name or name.endswith(f'-{p.name}'):
                        skill_dir = p
                        break

    if skill_dir:
        skill_file = skill_dir / 'SKILL.md'
        frontmatter = {}
        content = skill_file.read_text(encoding='utf-8', errors='replace')
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ':' in line:
                        k, v = line.split(':', 1)
                        frontmatter[k.strip()] = v.strip().strip('"\'')

        linked_agents = []
        for agent_key in CANONICAL_AGENTS.keys():
            agent_dir = get_agent_dir(effective_target_root, agent_key, is_global=is_global)
            agent_link = agent_dir / skill_dir.name
            try:
                if agent_link.is_symlink() and (agent_link.samefile(skill_dir) or agent_link.resolve() == skill_dir.resolve()):
                    linked_agents.append(agent_key)
            except OSError:
                pass

        print(f'Skill:        {skill_dir.name}')
        if frontmatter.get('name'):
            print(f'Display Name: {frontmatter.get("name")}')
        if frontmatter.get('description'):
            print(f'Description:  {frontmatter.get("description")}')
        print(f'Path:         {skill_dir}')
        print(f'Agents:       {", ".join(linked_agents) if linked_agents else "none"}')
        return

    resolved_package = resolve_package_name(name)
    data = fetch_repodata()
    packages = data.get('packages.conda', {}) | data.get('packages', {})
    found = [p for p in packages.values() if p.get('name') == resolved_package]
    if found:
        latest = sorted(found, key=lambda x: str(x.get('version', '0')))[-1]
        print(f'Package:      {latest.get("name")}')
        print(f'Version:      {latest.get("version")}')
        print(f'Summary:      {latest.get("summary", "No summary provided")}')
        print(f'License:      {latest.get("license", "Unknown")}')
        deps = latest.get('depends', [])
        if deps:
            print(f'Dependencies: {", ".join(deps)}')
        print('Status:       Available in channel (not installed in current environment)')
    else:
        print(f"Skill or package '{name}' not found.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    find = sub.add_parser('find', help='Search published skill package names and summaries')
    find.add_argument('query', nargs='?', default='')

    for command in ('add', 'remove', 'update', 'sync', 'list', 'info', 'clean', 'switch', 'manage'):
        p = sub.add_parser(command)
        if command in ('add', 'remove', 'info'):
            p.add_argument('package')
        elif command == 'switch':
            p.add_argument('target_environment')
        elif command == 'update':
            p.add_argument('package', nargs='?', default=None)
        elif command == 'sync':
            p.add_argument('--skill')
            p.add_argument('--prune', action='store_true', default=True,
                           help='Clean up stale symlinks pointing to deleted skills (default: true)')
        elif command == 'clean':
            p.add_argument('--all-envs', action='store_true', help='Clean skill symlinks across all Pixi environments')
        elif command == 'list':
            p.add_argument('-v', '--verbose', action='store_true', help='Show detailed agent link status')

        p.add_argument('-e', '--environment', default=None,
                       help='Target environment (default: configured in pixi.toml or "default")')
        p.add_argument('-g', '--global', dest='global_scope', action='store_true',
                       help='Use the persistent global skill workspace and home directory')
        if command not in ('find', 'info', 'list', 'switch'):
            p.add_argument('-a', '--agent', default=None,
                           help='Target agent(s): agents, claude, cursor, windsurf, copilot, or all (or aliases like codex, cline)')

    hook = sub.add_parser('hook', help='Pixi lifecycle integration hooks')
    hook_sub = hook.add_subparsers(dest='hook_action', required=True)
    hook_install = hook_sub.add_parser('install', help='Quietly sync skills after pixi install')
    hook_install.add_argument('-e', '--environment', default=None)
    hook_install.add_argument('-a', '--agent', default=None)
    hook_install.add_argument('--prune', action='store_true', default=True)

    args = parser.parse_args()

    root = project_root(Path.cwd()) if args.command != 'find' and not getattr(args, 'global_scope', False) else Path.cwd()
    target_root = None
    if args.command != 'find' and getattr(args, 'global_scope', False):
        env_name = getattr(args, 'environment', None) or 'default'
        target_root, root = global_workspace_root(env_name)
        args.environment = 'default'

    config = read_config(root) if not getattr(args, 'global_scope', False) else {}

    # Resolve default agent from config if not passed via CLI
    if getattr(args, 'agent', None) is None:
        cfg_agents = config.get('agents') or config.get('default_agents')
        if cfg_agents:
            args.agent = ','.join(cfg_agents) if isinstance(cfg_agents, list) else str(cfg_agents)
        else:
            args.agent = 'agents'

    # Resolve default environment from config if not passed via CLI
    if getattr(args, 'environment', None) is None:
        args.environment = config.get('environment') or config.get('default_environment') or 'default'

    if args.command != 'find' and not NAME.fullmatch(args.environment):
        raise ValueError('Invalid environment name')

    if args.command == 'find':
        find_skills(args.query)

    elif args.command == 'info':
        show_info(args.package, root, args.environment, target_root=target_root)

    elif args.command == 'add':
        pkg = resolve_package_name(args.package)
        agents = resolve_agents(args.agent)
        for agent in agents:
            plan_sync(root, args.environment, agent, allow_empty=True, target_root=target_root)
        if target_root is not None:
            root.mkdir(parents=True, exist_ok=True)
            manifest = root / 'pixi.toml'
            if not manifest.exists():
                subprocess.run(['pixi', 'init', '--format', 'pixi', '--channel',
                                'https://prefix.dev/conda-forge'], check=True, cwd=root)
        try:
            subprocess.run(['pixi', 'workspace', 'channel', 'add', '-e', args.environment, CHANNEL], check=True, cwd=root)
            subprocess.run(['pixi', 'add', '-e', args.environment, '--pinning-strategy', 'latest-up',
                            f'{CHANNEL}::{pkg}'], check=True, cwd=root)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Pixi could not add the package; the project channel may already have changed. '
                               'Inspect pixi.toml and pixi.lock before retrying.') from exc
        try:
            sync(root, args.environment, args.agent, target_root=target_root)
        except (ValueError, OSError) as exc:
            raise RuntimeError(f'Pixi added {pkg}, but agent synchronization failed: {exc}. '
                               'The manifest, lockfile, and environment may have changed; resolve the conflict '
                               'and run longred-skills sync.') from exc

    elif args.command == 'remove':
        pkg = resolve_package_name(args.package)
        try:
            subprocess.run(['pixi', 'remove', '-e', args.environment, pkg], check=True, cwd=root)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f'Pixi could not remove package {pkg}') from exc
        prune_agents = list(CANONICAL_AGENTS.keys()) if args.agent == 'agents' else resolve_agents(args.agent)
        prune_dangling(target_root or root, root, args.environment, prune_agents)
        print(f'Removed {pkg} and pruned associated agent links')

    elif args.command == 'update':
        cmd = ['pixi', 'update', '-e', args.environment]
        if args.package:
            pkg = resolve_package_name(args.package)
            cmd.append(pkg)
        try:
            subprocess.run(cmd, check=True, cwd=root)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Pixi update failed') from exc
        sync(root, args.environment, args.agent, target_root=target_root)

    elif args.command == 'sync':
        sync(root, args.environment, args.agent, args.skill, target_root=target_root, prune=args.prune)

    elif args.command == 'clean':
        clean(root, args.environment, args.agent, all_envs=args.all_envs, target_root=target_root)

    elif args.command == 'switch':
        switch_environment(root, args.target_environment, args.agent, target_root=target_root)

    elif args.command == 'manage':
        manage_interactive(root, args.environment, args.agent, target_root=target_root)

    elif args.command == 'hook':
        if args.hook_action == 'install':
            source = root / '.pixi' / 'envs' / args.environment / 'share' / 'agent-skills'
            if source.is_dir() and any(p.is_dir() for p in source.iterdir()):
                sync(root, args.environment, args.agent, target_root=target_root, prune=args.prune)

    else:  # list
        source = root / '.pixi' / 'envs' / args.environment / 'share' / 'agent-skills'
        if source.is_dir():
            effective_target_root = target_root or root
            is_global = target_root is not None
            for skill in sorted(source.iterdir()):
                if skill.is_dir() and (skill / 'SKILL.md').is_file():
                    if getattr(args, 'verbose', False):
                        linked = []
                        for agent_key in CANONICAL_AGENTS.keys():
                            agent_dir = get_agent_dir(effective_target_root, agent_key, is_global=is_global)
                            link = agent_dir / skill.name
                            try:
                                if link.is_symlink() and (link.samefile(skill) or link.resolve() == skill.resolve()):
                                    linked.append(agent_key)
                            except OSError:
                                pass
                        links_str = f" (linked: {', '.join(linked)})" if linked else " (not linked)"
                        print(f'{skill.name}{links_str}')
                    else:
                        print(skill.name)


def run():
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        print(f'longred-skills: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
