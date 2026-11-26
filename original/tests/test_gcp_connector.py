import sys,unittest,tempfile,json,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gcp_connector import asset_id,classify_sql,discover,export
class FakeDataset:
    dataset_id='gold'
class FakeField:
    name='amount';field_type='NUMERIC';mode='NULLABLE';description='';fields=[]
class FakeTable:
    table_id='mart';table_type='VIEW'
class FakeDetail:
    table_type='VIEW';schema=[FakeField()];description='sales';view_query='select * from `p1.silver.sales`'
class FakeClient:
    def list_datasets(self,project):return [FakeDataset()]
    def list_tables(self,ds):return [FakeTable()]
    def get_table(self,table):return FakeDetail()
class TestConnector(unittest.TestCase):
    def test_id(self):self.assertEqual(asset_id('p','d','t','c'),'bigquery://p/d/t#c')
    def test_sql_candidate(self):
        edges=classify_sql('select * from `p1.silver.sales`','bigquery://p1/gold/mart','view')
        self.assertEqual(edges[0]['confidence'],'CANDIDATE')
        self.assertFalse(edges[0]['execution_verified'])
    def test_discover_and_zip(self):
        cfg={'mode':'lineage','project_scope':'all','sources':['bigquery','dataform','scheduled','dbt']}
        r=discover(cfg,client=FakeClient(),project_provider=lambda:['p1'])
        self.assertEqual(r['counts']['columns'],1)
        self.assertEqual(r['counts']['lineage_edges'],1)
        self.assertEqual(r['source_status']['dataform'],'NOT_CONFIGURED')
        self.assertEqual(r['source_status']['scheduled'],'NOT_CONFIGURED')
        with tempfile.TemporaryDirectory() as d:
            path=export(r,Path(d)/'result.zip')
            with zipfile.ZipFile(path) as z:self.assertIn('lineage_edges.json',z.namelist())
if __name__=='__main__':unittest.main()
