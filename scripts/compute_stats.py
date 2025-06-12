import argparse
import json
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(__file__))
    import dependency_graph
else:
    from . import dependency_graph


def compute_stats(path='.', lean_path=None):
    """Return statistics about the Stacks Project dependency graph."""
    results, edges = dependency_graph.build_graph(path)
    stats = {
        'num_nodes': len(results),
        'num_edges': len(edges),
    }
    if lean_path:
        tag_map = dependency_graph.load_tag_map(path)
        lean_snippets = dependency_graph.scan_mathlib(lean_path, tag_map)
        stats['num_lean_snippets'] = len(lean_snippets)
        count = sum(1 for label in results if label in lean_snippets)
        stats['num_nodes_with_lean_snippet'] = count
    return stats


def main():
    parser = argparse.ArgumentParser(description='Compute statistics for the Stacks Project.')
    parser.add_argument('path', nargs='?', default='.', help='Path to Stacks Project root')
    parser.add_argument('--lean-path', help='Path to mathlib4 checkout')
    parser.add_argument('--json', action='store_true', help='Output JSON')
    args = parser.parse_args()

    stats = compute_stats(args.path, args.lean_path)

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        for k, v in stats.items():
            print(f'{k}: {v}')


if __name__ == '__main__':
    main()
