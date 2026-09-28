#!/usr/bin/env python3
"""Merge this Keller workspace and the pinned runtime into per-user Ars config."""

import argparse
import os
import runpy
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-root', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--device-root', required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--codex-binary')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    runtime = os.path.realpath(args.runtime_root)
    workspace = os.path.realpath(args.workspace)
    official = runpy.run_path(os.path.join(runtime, 'arsumbris', 'scripts', 'seed-device-config.py'))
    discover = official['discover_repos']
    scalar = official['yaml_scalar']
    read_repos = official['parse_repos_yaml']
    read_templates = official['parse_template_repos']
    existing_keys = official['existing_top_keys']
    roots = discover(runtime) + discover(workspace)
    target = os.path.join(args.device_root, 'au-engine', 'config', 'repos.yaml')
    previous = read_repos(target)
    seen = {}
    additions = []
    for name, path, _description in roots:
        path = os.path.realpath(path)
        if name in seen and seen[name] != path:
            raise ValueError(f'duplicate repo identity {name}: {seen[name]} and {path}')
        seen[name] = path
        if name in previous and os.path.realpath(previous[name]) != path:
            raise ValueError(f'{name} already registered at {previous[name]}; refusing to replace it with {path}')
        if name not in previous:
            additions.append((name, path))
    if previous and not os.path.isfile(target):
        raise ValueError('Unexpected missing registry')

    template = os.path.join(runtime, 'au-defaults')
    host = os.path.join(args.device_root, 'au-host', 'config')
    template_path = os.path.join(host, 'workspace-template-repos.yaml')
    add_template = template not in read_templates(template_path)
    paths_path = os.path.join(host, 'paths.yaml')
    expected = {
        'au': os.path.join(runtime, 'au-engine', 'target', 'release', 'au'),
        'au-mcp': os.path.join(runtime, 'au-mcp', 'src', 'cli.ts'),
        'node': args.node,
    }
    for path in expected.values():
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
    missing_paths = {k: v for k, v in expected.items() if k not in existing_keys(paths_path)}
    add_codex = False
    if args.codex_binary:
        binary = os.path.realpath(args.codex_binary)
        if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            raise ValueError('Codex binary must be an existing executable path')
        if os.path.isfile(paths_path):
            content = open(paths_path, encoding='utf-8').read()
            if 'binaries' in existing_keys(paths_path):
                if any(line.strip().startswith('codex:') for line in content.splitlines()):
                    print('Codex binary already registered; preserving existing path')
                else:
                    raise ValueError('Existing binaries map needs manual Codex entry; refusing to rewrite user config')
            else:
                add_codex = True
        else:
            add_codex = True
    if additions and os.path.isfile(target) and not any(line.strip() == 'repos:' for line in open(target, encoding='utf-8')):
        raise ValueError(f'Unrecognized repo registry format: {target}')
    if add_template and os.path.isfile(template_path) and not any(line.strip() == 'repos:' for line in open(template_path, encoding='utf-8')):
        raise ValueError(f'Unrecognized template registry format: {template_path}')
    print(f'registration: {len(additions)} new repositories, template {"add" if add_template else "present"}, '
          f'{len(missing_paths)} new tool paths ({"apply" if args.write else "dry run"})')
    for name, path in additions:
        print(f'  {name}: {path}')
    if not args.write:
        return

    def append(path, content, header):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old = open(path, encoding='utf-8').read() if os.path.isfile(path) else ''
        with open(path, 'a', encoding='utf-8') as stream:
            stream.write(('' if not old or old.endswith('\n') else '\n') + (header if not old else '') + content)

    if additions:
        append(target, ''.join(f'  - name: {scalar(name)}\n    path: {scalar(path)}\n'
                               for name, path in additions), 'repos:\n')
    if add_template:
        append(template_path, f'  - path: {scalar(template)}\n', 'repos:\n')
    if missing_paths:
        append(paths_path, ''.join(f'{name}: {scalar(path)}\n' for name, path in missing_paths.items()), '')
    if add_codex:
        append(paths_path, f'binaries:\n  codex: {scalar(binary)}\n', '')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(f'registration failed: {error}', file=sys.stderr)
        sys.exit(1)
