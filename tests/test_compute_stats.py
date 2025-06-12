import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.compute_stats import compute_stats

class ComputeStatsTests(unittest.TestCase):
    def test_compute_stats_with_lean(self):
        with tempfile.TemporaryDirectory() as d:
            # prepare minimal Stacks layout
            os.makedirs(os.path.join(d, 'tags'))
            with open(os.path.join(d, 'tags', 'tags'), 'w') as f:
                f.write('ABCD,sample-label-foo\n')
            with open(os.path.join(d, 'Makefile'), 'w') as f:
                f.write('LIJST = sample\n')
            with open(os.path.join(d, 'sample.tex'), 'w') as f:
                f.write('\\begin{lemma}\n')
                f.write('\\label{label-foo}\n')
                f.write('A\\end{lemma}\n')
            # minimal mathlib with stacks attribute
            ml = os.path.join(d, 'ml')
            os.makedirs(ml)
            with open(os.path.join(ml, 'test.lean'), 'w') as f:
                f.write('@[stacks ABCD]\nlemma foo : True := by trivial\n')
            stats = compute_stats(d, ml)
            self.assertEqual(stats['num_lean_snippets'], 1)
            self.assertEqual(stats['num_nodes_with_lean_snippet'], 1)

    def test_nodes_with_lean_snippet_count(self):
        """Only nodes referenced in mathlib should be counted."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'tags'))
            with open(os.path.join(d, 'tags', 'tags'), 'w') as f:
                f.write('ABCD,foo-label-foo\nEFGH,bar-label-bar\n')
            with open(os.path.join(d, 'Makefile'), 'w') as f:
                f.write('LIJST = foo bar\n')
            with open(os.path.join(d, 'foo.tex'), 'w') as f:
                f.write('\\begin{lemma}\n\\label{label-foo}\nA\\end{lemma}\n')
            with open(os.path.join(d, 'bar.tex'), 'w') as f:
                f.write('\\begin{lemma}\n\\label{label-bar}\nB\\end{lemma}\n')
            ml = os.path.join(d, 'ml')
            os.makedirs(ml)
            with open(os.path.join(ml, 'ref.lean'), 'w') as f:
                f.write('@[stacks ABCD]\nlemma foo : True := by trivial\n')
            stats = compute_stats(d, ml)
            self.assertEqual(stats['num_nodes'], 2)
            self.assertEqual(stats['num_lean_snippets'], 1)
            self.assertEqual(stats['num_nodes_with_lean_snippet'], 1)

if __name__ == '__main__':
    unittest.main()
