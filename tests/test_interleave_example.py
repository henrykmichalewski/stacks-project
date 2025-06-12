import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.dependency_graph import generate_dependency_tex


class InterleaveExampleTest(unittest.TestCase):
    def test_interleave_multiple_lines(self):
        with tempfile.TemporaryDirectory() as d:
            sample = os.path.join(d, 'sample.tex')
            with open(sample, 'w') as f:
                f.write('\\begin{lemma}\\label{lemma-a}\n')
                f.write('For $n \\ge 0$ we have $\\sum_{i=0}^n i = n(n+1)/2$.\\n')
                f.write('\\end{lemma}\n')
            results = {
                'sample-lemma-a': {
                    'type': 'lemma',
                    'file': 'sample',
                    'label': 'lemma-a',
                }
            }
            edges = []
            snippet = (
                'lemma lemma_a (n : Nat) :\\n'
                '  (Finset.range (n + 1)).sum id = n * (n + 1) / 2 := by\\n'
                '  simpa using Nat.sum_range_id n'
            )
            snips = {'sample-lemma-a': snippet}
            out = os.path.join(d, 'out.tex')
            generate_dependency_tex('sample-lemma-a', results, edges, d, out, snips, interleave=True)
            with open(out) as f:
                data = f.read()
            self.assertIn('Finset.range', data)
            self.assertIn('minipage', data)


if __name__ == '__main__':
    unittest.main()
