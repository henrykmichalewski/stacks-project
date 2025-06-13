import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.interleaved_dep_graph import (
    StacksParser,
    LeanParser,
    DependencyGraphBuilder,
    Exporter,
)


def make_stacks(tmp: Path) -> Path:
    (tmp / 'tags').mkdir()
    (tmp / 'tags' / 'tags').write_text('ABCD,lemma-a\n')
    tex = tmp / 'sample.tex'
    tex.write_text(
        '\n'.join([
            '\\begin{lemma}',
            '\\label{lemma-a}',
            'See \\ref{lemma-b}.',
            '\\end{lemma}',
            '\\begin{lemma}',
            '\\label{lemma-b}',
            'Ok.',
            '\\end{lemma}',
        ])
    )
    return tmp


def make_mathlib(tmp: Path) -> Path:
    ml = tmp / 'ml'
    ml.mkdir()
    (ml / 'test.lean').write_text(
        '/-- Stacks Tag ABCD -/\nlemma foo : True := by\n  trivial\n'
    )
    return ml


def test_parsers_and_graph(tmp_path: Path):
    stacks_root = make_stacks(tmp_path)
    ml_root = make_mathlib(tmp_path)

    sp = StacksParser(stacks_root)
    sp.parse()
    assert 'lemma-a' in sp.envs
    assert sp.envs['lemma-a'].refs == {'lemma-b'}

    lp = LeanParser(ml_root)
    lp.parse()
    assert 'ABCD' in lp.snippets

    builder = DependencyGraphBuilder(sp, lp)
    builder.build('lemma-a')
    G = builder.G
    assert 'lemma-a' in G.nodes
    assert ('lemma-a', 'lemma-b') in G.edges
    assert G.nodes['lemma-a']['lean'].startswith('lemma foo')

    out_json = tmp_path / 'graph.json'
    Exporter(G).to_json(out_json)
    data = json.loads(out_json.read_text())
    assert any(n['id'] == 'lemma-a' for n in data['nodes'])
