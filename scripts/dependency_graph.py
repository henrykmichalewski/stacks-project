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
            if dst in results and src in results:
                f.write(f'  "{src}" -> "{dst}";\n')
        f.write('}\n')


def subgraph(label, results, edges):
    """Return nodes and edges reachable from ``label``."""
    adj = {}
    for src, dst in edges:
        adj.setdefault(src, []).append(dst)

    visited = set()
    stack = [label]
    while stack:
        node = stack.pop()
        if node in visited or node not in results:
            continue
        visited.add(node)
        stack.extend(adj.get(node, []))

    sub_results = {l: results[l] for l in visited}
    sub_edges = [(s, d) for s, d in edges if s in visited and d in visited]
    return sub_results, sub_edges


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


def generate_dependency_tex(label, results, edges, path, outfile):
    """Write a TeX file with ``label`` and all its dependencies."""
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

    with open(outfile, 'w') as f:
        f.write('\\documentclass{article}\n')
        f.write('\\begin{document}\n')
        for lbl in order:
            for line in _extract_environment(path, lbl, results):
                f.write(line)
        f.write('\\end{document}\n')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Generate dependency graph for Stacks Project.')
    parser.add_argument('path', nargs='?', default='.', help='Path to Stacks Project root')
    parser.add_argument('--dot', default='deps.dot', help='Output DOT file')
    parser.add_argument('--single', metavar='LABEL', help='Only include LABEL and its dependencies in the DOT file')
    parser.add_argument('--json', action='store_true', help='Also output JSON data')
    parser.add_argument('--tex', metavar='LABEL', help='Generate TeX file for theorem LABEL and its deps')
    parser.add_argument('--tex-out', default='deps.tex', help='TeX output file (with --tex)')
    args = parser.parse_args()

    results, edges = build_graph(args.path)
    if args.single:
        sub_results, sub_edges = subgraph(args.single, results, edges)
        write_dot(sub_results, sub_edges, args.dot)
    else:
        write_dot(results, edges, args.dot)
    if args.json:
        with open('deps.json', 'w') as j:
            json.dump({'nodes': results, 'edges': edges}, j, indent=2)
    if args.tex:
        generate_dependency_tex(args.tex, results, edges, args.path, args.tex_out)


if __name__ == '__main__':
    main()
