import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.dependency_graph import load_tag_map, scan_mathlib, generate_dependency_tex

class DependencyGraphTests(unittest.TestCase):
    def test_load_tag_map(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'tags'))
            with open(os.path.join(d, 'tags', 'tags'), 'w') as f:
                f.write('0001,label-foo\n0002,label-bar\n')
            mp = load_tag_map(d)
            self.assertEqual(mp['0001'], 'label-foo')
            self.assertEqual(mp['0002'], 'label-bar')

    def test_scan_mathlib(self):
        with tempfile.TemporaryDirectory() as d:
            tag_map = {'0001': 'label-foo'}
            with open(os.path.join(d, 'test.lean'), 'w') as f:
                f.write('lemma foo : True := by\n')
                f.write('  -- https://stacks.math.columbia.edu/tag/0001\n')
                f.write('  trivial\n')
            with open(os.path.join(d, 'attr.lean'), 'w') as f:
                f.write('@[stacks 0001]\n')
                f.write('def bar : True := by trivial\n')
            with open(os.path.join(d, 'doc.lean'), 'w') as f:
                f.write('''/-- Stacks Tag 0001 -/\nlemma baz : True := by trivial\n''')
            res = scan_mathlib(d, tag_map)
            self.assertIn('label-foo', res)
            snippet = res['label-foo']
            self.assertRegex(snippet, r'(lemma|def) (foo|bar|baz)')

    def test_generate_dependency_tex(self):
        with tempfile.TemporaryDirectory() as d:
            sample = os.path.join(d, 'sample.tex')
            with open(sample, 'w') as f:
                f.write('\\begin{lemma}\\label{lemma-a}A\\end{lemma}\n')
                f.write('\\begin{lemma}\\label{lemma-b}\\ref{lemma-a}\\end{lemma}\n')
            results = {
                'sample-lemma-a': {'type': 'lemma', 'file': 'sample', 'label': 'lemma-a'},
                'sample-lemma-b': {'type': 'lemma', 'file': 'sample', 'label': 'lemma-b'},
            }
            edges = [('sample-lemma-b', 'sample-lemma-a')]
            snips = {'sample-lemma-a': 'lemma foo : True := by trivial'}
            out = os.path.join(d, 'out.tex')
            generate_dependency_tex('sample-lemma-b', results, edges, d, out, snips)
            with open(out) as f:
                data = f.read()
            self.assertIn('lemma foo', data)

if __name__ == '__main__':
    unittest.main()
