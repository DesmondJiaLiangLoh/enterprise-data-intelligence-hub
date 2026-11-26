import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from app import app,explorer_sources
except ImportError:
    app=None
    explorer_sources=None
@unittest.skipIf(app is None,"Flask not installed in test environment")
class TestPortalControls(unittest.TestCase):
    def test_explorer_source_unique(self):
        entries=explorer_sources()
        self.assertEqual(len(entries),len({x['id'] for x in entries}))
        self.assertTrue(all(x['sources'] for x in entries))
    def test_termination_invalid_run(self):
        with app.test_client() as c:
            self.assertEqual(c.post('/api/runs/invalid/terminate').status_code,404)
    def test_termination_cross_origin(self):
        with app.test_client() as c:
            self.assertEqual(c.post('/api/runs/20260101T000000Z_12345678/terminate',headers={'Origin':'https://evil.example'}).status_code,403)
if __name__=='__main__':unittest.main()
