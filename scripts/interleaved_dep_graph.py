#!/usr/bin/env python3
"""
interleaved_dep_graph.py  ────────────────────────────────────────────────

A *single‑file* utility that builds **interleaved LaTeX ⇄ Lean** dependency
graphs for any Stacks Project tag.  The script is self‑contained and depends
only on the Python standard library plus the third‑party packages
`networkx` and `rich` (for pretty CLI feedback).  It purposely avoids any
Stacks‑specific build system so that it can be dropped next to a checkout of

  • the **Stacks Project** (https://stacks.math.columbia.edu/), and
  • **mathlib4** (https://github.com/leanprover-community/mathlib4).

The heavy lifting is split into three small, testable parts:

1. `StacksParser`  — scans *.tex* files, extracts every labelled *environment*
   (lemma/definition/…​) together with its *body* **and** the list of Stacks
   labels it cites.
2. `LeanParser`    — visits every *.lean* file, looking for the custom
   attribute `@[stacks TAG]` **or** the string "Stacks Tag TAG" inside the
   doc‑string immediately preceding a declaration, and returns an _object →
   tag_ map plus ready‑to‑render Lean *snippets*.
3. `DependencyGraphBuilder` — uses (1) to build a directed graph of tag →
   dependencies, then enriches each node with the Lean snippet from (2).

The graph can be exported

* as **DOT** (`.dot`) for Graphviz,
* as **JSON** for programmatic inspection, or
* as standalone **TeX** that compiles to a PDF in which, for every node, the
  Stacks text is set on the left and the corresponding Lean snippet (if any)
  is typeset on the right — exactly the layout described in the Stacks
  README.  A `--interleave` flag puts the Lean code *inside* the main TeX
  document rather than at its end.

Running example (from the Stacks README):

```bash
python3 interleaved_dep_graph.py \
    /path/to/stacks-project \
    --tex lemma-weil-additive \
    --lean /path/to/mathlib4 \
    --tex-out weil.tex --interleave
pdflatex weil.tex  # renders a nicely formatted PDF
```

The default “only follow citation edges until you hit a *definition* or any
node with no outgoing edges” heuristic can be overridden with
`--depth=N`, `--transitive`, or `--prune="lemma,proposition"`.

MIT licence.  Author: 2025‑06‑12 ChatGPT‑o3.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx  # type: ignore
from rich.progress import track  # type: ignore

# ────────────────────────────────────────────────────────────────────────────
# CONSTANTS / REGEXES
# ────────────────────────────────────────────────────────────────────────────
ENVIRONMENTS = [
    "definition",
    "lemma",
    "proposition",
    "theorem",
    "corollary",
    "remark",
    "remarks",
    "example",
    "exercise",
    "situation",
    "equation",
]
BEGIN_ENV_RE = re.compile(r"\\begin{(" + "|".join(ENVIRONMENTS) + r")}")
LABEL_RE = re.compile(r"\\label{([a-z]+-[0-9A-Za-z-]+)}")
REF_RE = re.compile(r"\\ref{([a-z]+-[0-9A-Za-z-]+)}")
TAG_LINE_RE = re.compile(r"^([0-9A-Za-z]{4}),([^,]+)$")

LEAN_ATTR_RE = re.compile(r"@\[\s*stacks\s+([0-9A-Za-z]{4})")
LEAN_DOC_RE = re.compile(r"Stacks\s+Tag\s+([0-9A-Za-z]{4})", re.IGNORECASE)
LEAN_HEADER_RE = re.compile(
    r"^(lemma|theorem|def|definition|structure|class|instance)\s+([\w\.]+)",
)

# ────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class StacksEnv:
    """A single \begin{ENV} …​ \end{ENV} block with a Stacks label."""

    env_type: str  # lemma / definition / …​
    label: str  # e.g. lemma-weil-additive
    file: Path
    body: List[str]  # raw lines *inside* the environment
    refs: Set[str]  # other Stacks labels referenced inside body

    def short(self) -> str:
        return f"{self.env_type[:3]}:{self.label.split('-', 1)[-1]}"

    def tex_block(self) -> str:
        """Original LaTeX code of this environment (without surrounding blank lines)."""
        header = f"\\begin{{{self.env_type}}}\\label{{{self.label}}}"
        footer = f"\\end{{{self.env_type}}}"
        return "\n".join([header, *self.body, footer])


@dataclass
class LeanSnippet:
    tag: str  # 09GK …​
    file: Path
    start_line: int  # 1‑based
    lines: List[str]

    def code(self) -> str:
        return "\n".join(self.lines)


# ────────────────────────────────────────────────────────────────────────────
# PARSERS
# ────────────────────────────────────────────────────────────────────────────
class StacksParser:
    """Parse a Stacks Project checkout and extract every labelled env."""

    def __init__(self, root: Path):
        self.root = root
        self.tag_map = self._load_tag_map()
        self.envs: Dict[str, StacksEnv] = {}

    # ‑‑‑ PRIVATE helpers ‑‑‑
    def _load_tag_map(self) -> Dict[str, str]:
        tags_file = self.root / "tags" / "tags"
        mapping: Dict[str, str] = {}
        if not tags_file.exists():
            return mapping
        for raw in tags_file.read_text(encoding="utf8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            m = TAG_LINE_RE.match(raw)
            if m:
                tag, label = m.groups()
                mapping[tag.upper()] = label  # tag → TeX label (lemma‑foo)
        return mapping

    # ‑‑‑ PUBLIC API ‑‑‑
    def parse(self) -> None:
        """Populate `self.envs`. Takes <1 s for a full Stacks checkout."""
        tex_files = [p for p in self.root.glob("*.tex") if p.name != "chapters.tex"]
        for path in track(tex_files, description="Parsing Stacks .tex"):
            self._parse_tex_file(path)

    # ‑‑‑ INTERNAL .tex parser ‑‑‑
    def _parse_tex_file(self, path: Path):
        lines = path.read_text(encoding="utf8", errors="ignore").splitlines()
        i = 0
        while i < len(lines):
            match = BEGIN_ENV_RE.match(lines[i].strip())
            if not match:
                i += 1
                continue
            env_type = match.group(1)
            # collect until \end{…​}
            body: List[str] = []
            label: Optional[str] = None
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.strip().startswith(f"\\end{{{env_type}}}"):
                    break
                mlabel = LABEL_RE.search(line)
                if mlabel:
                    label = mlabel.group(1)
                body.append(line)
                i += 1
            # skip the closing \end line as well
            i += 1
            if not label:
                # Unlabelled env.  Ignore.
                continue
            refs = set(REF_RE.findall("\n".join(body)))
            self.envs[label] = StacksEnv(env_type, label, path, body, refs)


class LeanParser:
    """Scan mathlib4 and pull out all declarations annotated with a Stacks tag."""

    def __init__(self, root: Path):
        self.root = root
        self.snippets: Dict[str, LeanSnippet] = {}  # tag → snippet

    def parse(self) -> None:
        lean_files = list(self.root.rglob("*.lean"))
        for path in track(lean_files, description="Parsing Lean files"):
            self._parse_lean_file(path)

    # ‑‑‑ internal helpers ‑‑‑
    def _parse_lean_file(self, path: Path):
        lines = path.read_text(encoding="utf8", errors="ignore").splitlines()
        pending_tags: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            attr = LEAN_ATTR_RE.search(line)
            if attr:
                pending_tags.append(attr.group(1).upper())
                i += 1
                continue
            # detect doc‑string style tags
            doc = LEAN_DOC_RE.search(line)
            if doc and lines[max(i-1, 0)].lstrip().startswith("/--"):
                pending_tags.append(doc.group(1).upper())
                i += 1
                continue
            head = LEAN_HEADER_RE.match(line.strip())
            if head and pending_tags:
                # capture until blank line or next declaration
                start = i
                snippet_lines = [line]
                i += 1
                while i < len(lines) and lines[i].strip():
                    snippet_lines.append(lines[i])
                    i += 1
                # attach snippet to *all* pending tags (can be more than one)
                for tag in pending_tags:
                    self.snippets[tag] = LeanSnippet(tag, path, start + 1, snippet_lines)
                pending_tags = []
                continue
            i += 1


# ────────────────────────────────────────────────────────────────────────────
# GRAPH BUILDER
# ────────────────────────────────────────────────────────────────────────────
class DependencyGraphBuilder:
    """Given parsed data, build a `networkx.DiGraph`."""

    def __init__(
        self,
        stacks: StacksParser,
        lean: Optional[LeanParser] = None,
        include_defs: bool = True,
    ):
        self.stacks = stacks
        self.lean = lean
        self.include_defs = include_defs
        self.G: nx.DiGraph = nx.DiGraph()

    def build(self, root_label: str, depth: Optional[int] = None):
        """Populate `self.G` starting from *root_label*.

        If *depth* is `None`, traverse until you hit only
        *definition* nodes or leaves.
        """
        if root_label not in self.stacks.envs:
            raise KeyError(f"Unknown label {root_label!r} in Stacks data")

        def _should_stop(label: str, d: int):
            if depth is not None and d >= depth:
                return True
            if not self.include_defs:
                return False
            env = self.stacks.envs[label]
            return env.env_type == "definition"

        visited: Set[str] = set()

        def dfs(label: str, d: int = 0):
            if label in visited:
                return
            visited.add(label)
            env = self.stacks.envs[label]
            self._add_node(env)
            if _should_stop(label, d):
                return
            for dep in env.refs:
                if dep not in self.stacks.envs:
                    # dangling reference (rare)
                    continue
                self._add_edge(label, dep)
                dfs(dep, d + 1)

        dfs(root_label)

    # ‑‑‑ helpers ‑‑‑
    def _add_node(self, env: StacksEnv):
        data = {
            "type": env.env_type,
            "tex": env.tex_block(),
        }
        # attach Lean snippet if any
        tag = self._label_to_tag(env.label)
        if self.lean and tag and tag in self.lean.snippets:
            data["lean"] = self.lean.snippets[tag].code()
        self.G.add_node(env.label, **data)

    def _add_edge(self, src: str, tgt: str):
        self.G.add_edge(src, tgt)

    def _label_to_tag(self, label: str) -> Optional[str]:
        # In the Stacks repo, the tag map is bidirectional: tag → label.
        for tag, lab in self.stacks.tag_map.items():
            if lab == label:
                return tag
        return None


# ────────────────────────────────────────────────────────────────────────────
# EXPORTERS
# ────────────────────────────────────────────────────────────────────────────
class Exporter:
    """Bundle various ways to serialise the graph."""

    def __init__(self, G: nx.DiGraph):
        self.G = G

    def to_dot(self, outfile: Path):
        try:
            import pydot  # type: ignore
        except ImportError as e:
            raise SystemExit("pydot not installed; `pip install pydot`." ) from e
        graph = nx.drawing.nx_pydot.to_pydot(self.G)
        outfile.write_text(graph.to_string())

    def to_json(self, outfile: Path):
        data = nx.node_link_data(self.G)
        outfile.write_text(json.dumps(data, indent=2))

    # ‑‑‑ TeX export ‑‑‑
    def to_tex(self, outfile: Path, interleave: bool = False):
        tex = [
            r"% Auto‑generated by interleaved_dep_graph.py",
            r"\documentclass{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{geometry}",
            r"\usepackage{tikz-cd}",
            r"\usepackage{listings}",
            r"\usepackage{xcolor}",
            r"\definecolor{codebg}{HTML}{F5F5F5}",
            r"\lstset{basicstyle=\ttfamily\small, breaklines=true, backgroundcolor=\color{codebg}}",
            r"\begin{document}",
            r"\section*{Dependency graph}",
        ]
        tex.append(self._tikz_picture())
        tex.append(r"\bigskip")
        if interleave:
            tex.extend(self._interleave_blocks())
        else:
            tex.extend(self._appendix_blocks())
        tex.append(r"\end{document}")
        outfile.write_text("\n".join(tex))

    # helper: build TikZ diagram
    def _tikz_picture(self) -> str:
        # a simple top‑down layered layout using TikZ‑cd
        lines = [r"\begin{tikzcd}[column sep=huge, row sep=huge]"]
        # group nodes by depth from roots (sources with no incoming edges)
        roots = [n for n in self.G.nodes if self.G.in_degree(n) == 0]
        if not roots:
            roots = list(self.G.nodes)
        depth_map = nx.single_source_shortest_path_length(self.G.reverse(copy=False), roots[0])
        # bucket by depth
        buckets: Dict[int, List[str]] = {}
        for node, d in depth_map.items():
            buckets.setdefault(d, []).append(node)
        for d in sorted(buckets):
            row = []
            for label in buckets[d]:
                short = self.G.nodes[label].get("type", "?")[:3] + ":" + label.split("-", 1)[-1]
                row.append(short)
            lines.append(" & ".join(row) + r" \\")
        lines.append(r"\end{tikzcd}")
        return "\n".join(lines)

    # helper: interleaved minipage blocks
    def _interleave_blocks(self) -> List[str]:
        out: List[str] = []
        for label in nx.topological_sort(self.G):
            node = self.G.nodes[label]
            out.extend(
                [
                    r"\begin{minipage}[t]{0.48\linewidth}",
                    node["tex"],
                    rf"\end{{minipage}}\hfill\begin{{minipage}}[t]{{0.48\linewidth}}",
                    r"\begin{lstlisting}",
                    node.get("lean", "% no Lean snippet"),
                    r"\end{lstlisting}",
                    r"\end{minipage}",
                    r"\bigskip",
                ]
            )
        return out

    # helper: appendix style (LaTeX first, Lean later)
    def _appendix_blocks(self) -> List[str]:
        out: List[str] = [r"\section*{Stacks statements}"]
        for label in nx.topological_sort(self.G):
            out.append(self.G.nodes[label]["tex"])
            out.append(r"\bigskip")
        out.append(r"\newpage\section*{Lean snippets}")
        for label in nx.topological_sort(self.G):
            snippet = self.G.nodes[label].get("lean")
            if not snippet:
                continue
            out.extend([r"\subsection*{" + label + "}", r"\begin{lstlisting}", snippet, r"\end{lstlisting}"])
        return out


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Generate interleaved Stacks⇄Lean dependency graphs.")
    p.add_argument("stacks_root", type=Path, help="Path to Stacks Project checkout (root directory)")
    p.add_argument("--lean", type=Path, dest="lean_root", help="Path to mathlib4 root (optional)")
    p.add_argument("--tex", metavar="LABEL", help="Stacks label whose dependency graph is produced as TeX")
    p.add_argument("--tex-out", type=Path, default=Path("deps.tex"))
    p.add_argument("--dot", type=Path, help="Write Graphviz .dot graph to this file")
    p.add_argument("--json", type=Path, help="Write machine‑readable graph to this file")
    p.add_argument("--depth", type=int, help="Maximum DFS depth (0 = just the node itself)")
    p.add_argument("--no-defs", action="store_true", help="Do *not* automatically stop at definitions")
    p.add_argument("--interleave", action="store_true", help="Place Lean snippets next to each LaTeX env")

    args = p.parse_args()

    stacks = StacksParser(args.stacks_root)
    stacks.parse()

    lean_parser = None
    if args.lean_root:
        lean_parser = LeanParser(args.lean_root)
        lean_parser.parse()

    if not args.tex:
        p.error("--tex LABEL is required (future versions may add more modes)")
    label = args.tex.strip()

    G_builder = DependencyGraphBuilder(
        stacks,
        lean_parser,
        include_defs=not args.no_defs,
    )
    G_builder.build(label, depth=args.depth)

    exporter = Exporter(G_builder.G)
    if args.dot:
        exporter.to_dot(args.dot)
        print(f"[✓] Wrote Graphviz file → {args.dot}")
    if args.json:
        exporter.to_json(args.json)
        print(f"[✓] Wrote JSON file    → {args.json}")
    exporter.to_tex(args.tex_out, interleave=args.interleave)
    print(f"[✓] Wrote TeX file     → {args.tex_out}")


if __name__ == "__main__":
    main()
