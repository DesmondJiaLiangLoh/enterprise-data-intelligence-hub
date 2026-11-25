import unittest
from hub import match,run
class Tests(unittest.TestCase):
 def test_match(self):
  self.assertEqual(match('product margin')[0]['name'],'Product profitability'); self.assertEqual(match('unmatched'),[])
 def test_graph(self):
  g=run()['WF3']; self.assertEqual(len(g['nodes']),5); self.assertEqual(len(g['edges']),5)
