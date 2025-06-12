import os
import re
import json

# List of environments we consider
ENVIRONMENTS = [
    'definition', 'lemma', 'proposition', 'theorem',
    'remark', 'remarks', 'example', 'exercise',
    'situation', 'equation'
]

# Prefixes used for labels we track
PREFIXES = tuple(env + '-' for env in ENVIRONMENTS)


def load_tag_map(path):
    """Return mapping of Stacks tag numbers to labels."""
    tag_file = os.path.join(path, 'tags', 'tags')
    tag_map = {}
    if not os.path.exists(tag_file):
        return tag_map
    with open(tag_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) == 2:
                tag_map[parts[0]] = parts[1]
    return tag_map


def scan_mathlib(path, tag_map):
    """Return mapping from Stacks labels to Lean code snippets."""
    results = {}
    tag_re = re.compile(r'https://stacks\.math\.columbia\.edu/tag/([0-9A-Za-z]+)')
    env_re = re.compile(r'^(lemma|theorem|def|definition)\s+([\w\.]*)')
    for root, _, files in os.walk(path):
        for name in files:
            if not name.endswith('.lean'):
                continue
            filename = os.path.join(root, name)
            try:
                with open(filename, 'r') as f:
                    lines = f.readlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                m = tag_re.search(line)
                if not m:
                    continue
                tag = m.group(1).upper()
                label = tag_map.get(tag)
                if not label:
                    continue
                # search upwards for lemma/def line
                j = i
                while j >= 0 and not env_re.search(lines[j]):
                    j -= 1
                start = max(j, 0)
                snippet = ''.join(lines[start:i+3])
                results[label] = snippet
    return results


def list_text_files(path):
    """Return stems of TeX files listed in the Makefile."""
    with open(os.path.join(path, 'Makefile'), 'r') as f:
        for line in f:
            if line.startswith('LIJST = '):
                break
        items = ''
        while line.rstrip().endswith('\\'):
            items += ' ' + line.rstrip().rstrip('\\')
            line = f.readline()
        items += ' ' + line
        items = items.replace('LIJST = ', '')
        return items.split()


def parse_file(path, name, results, edges):
    filename = os.path.join(path, name + '.tex')
    if not os.path.exists(filename):
        return
    env_type = None
    label = None
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if env_type is None:
                m = re.match(r'\\begin{(' + '|'.join(ENVIRONMENTS) + ')}', line)
                if m:
                    env_type = m.group(1)
                    label = None
                continue
            else:
                if label is None:
                    m = re.match(r'\\label{([^}]+)}', line)
                    if m:
                        label = m.group(1)
                        results[label] = {
                            'type': env_type,
                            'file': name
                        }
                        continue
                for ref in re.findall(r'\\ref{([^}]+)}', line):
                    if ref.startswith(PREFIXES) and label:
                        edges.append((label, ref))
                if re.match(r'\\end{' + env_type + '}', line):
                    env_type = None
                    label = None


def build_graph(path):
    results = {}
    edges = []
    for name in list_text_files(path):
        parse_file(path, name, results, edges)
    return results, edges


def write_dot(results, edges, outfile):
    with open(outfile, 'w') as f:
        f.write('digraph StacksProject {\n')
        f.write('  node [shape=box];\n')
        for label, data in results.items():
            node_label = f"{label}\n({data['file']})"
            f.write(f'  "{label}" [label="{node_label}"];\n')
        for src, dst in edges:
            if dst in results:
                f.write(f'  "{src}" -> "{dst}";\n')
        f.write('}\n')


def _extract_environment(path, label, results):
    """Return lines of the environment containing ``label``."""
    info = results.get(label)
    if not info:
        return []
    filename = os.path.join(path, info['file'] + '.tex')
    lines = []
    collecting = False
    env_type = None
    with open(filename, 'r') as f:
        for line in f:
            if not collecting:
                if env_type is None:
                    m = re.match(r'\\begin{(' + '|'.join(ENVIRONMENTS) + ')}', line)
                    if m:
                        env_type = m.group(1)
                        lines = [line]
                    continue
                else:
                    lines.append(line)
                    if re.search(r'\\label{' + re.escape(label) + '}', line):
                        collecting = True
                    if re.match(r'\\end{' + env_type + '}', line):
                        env_type = None
                        lines = []
            else:
                lines.append(line)
                if re.match(r'\\end{' + env_type + '}', line):
                    break
    return lines


def generate_dependency_tex(label, results, edges, path, outfile, lean_snippets=None):
    """Write a TeX file with ``label`` and all its dependencies.
    If ``lean_snippets`` is provided, include corresponding Lean code."""
    adj = {}
    for src, dst in edges:
        adj.setdefault(src, []).append(dst)

    order = []
    visited = set()

    def visit(node):
        if node in visited or node not in results:
            return
        visited.add(node)
        for dep in adj.get(node, []):
            visit(dep)
        order.append(node)

    visit(label)

    lean_snippets = lean_snippets or {}
    with open(outfile, 'w') as f:
        f.write('\\documentclass{article}\n')
        f.write('\\begin{document}\n')
        for lbl in reversed(order):
            for line in _extract_environment(path, lbl, results):
                f.write(line)
            snippet = lean_snippets.get(lbl)
            if snippet:
                f.write('\\begin{verbatim}\n')
                f.write(snippet)
                if not snippet.endswith('\n'):
                    f.write('\n')
                f.write('\\end{verbatim}\n')
        f.write('\\end{document}\n')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Generate dependency graph for Stacks Project.')
    parser.add_argument('path', nargs='?', default='.', help='Path to Stacks Project root')
    parser.add_argument('--dot', default='deps.dot', help='Output DOT file')
    parser.add_argument('--json', action='store_true', help='Also output JSON data')
    parser.add_argument('--tex', metavar='LABEL', help='Generate TeX file for theorem LABEL and its deps')
    parser.add_argument('--tex-out', default='deps.tex', help='TeX output file (with --tex)')
    parser.add_argument('--lean-path', help='Path to mathlib4 for Lean snippets')
    args = parser.parse_args()

    results, edges = build_graph(args.path)
    write_dot(results, edges, args.dot)
    if args.json:
        with open('deps.json', 'w') as j:
            json.dump({'nodes': results, 'edges': edges}, j, indent=2)
    lean_snippets = None
    if args.lean_path:
        tag_map = load_tag_map(args.path)
        lean_snippets = scan_mathlib(args.lean_path, tag_map)
    if args.tex:
        generate_dependency_tex(args.tex, results, edges, args.path, args.tex_out, lean_snippets)


if __name__ == '__main__':
    main()
