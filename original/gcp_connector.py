"""Read-only GCP metadata discovery. No business rows or transformation execution."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, re, sys, zipfile
from pathlib import Path

SCHEMA_VERSION='1.0'
def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()
def asset_id(project,dataset,table=None,column=None):
    base=f'bigquery://{project}/{dataset}'
    if table is not None: base+='/'+table
    if column is not None: base+='#'+column
    return base

def classify_sql(sql, target, source_ref):
    """Conservative table-reference parser; edges are CANDIDATE until verified."""
    edges=[]
    # Backtick qualified references only; never infer from unqualified names.
    refs=set(re.findall(r'`([\w-]+)\.([\w-]+)\.([\w$-]+)`',sql or ''))
    for project,dataset,table in sorted(refs):
        source=asset_id(project,dataset,table)
        if source==target:continue
        edges.append({'source_id':source,'target_id':target,'relationship_type':'REFERENCES','evidence_type':'SQL_TEXT_REFERENCE','confidence':'CANDIDATE','execution_verified':False,'source_reference':source_ref})
    return edges

def discover(config, client=None, project_provider=None, dataform_provider=None, scheduled_provider=None):
    """Dependency injection enables offline tests. APIs accessed only for metadata."""
    if client is None:
        from google.cloud import bigquery
        client=bigquery.Client(project=config.get('billing_project') or None)
    if project_provider is None:
        from google.cloud import resourcemanager_v3
        pclient=resourcemanager_v3.ProjectsClient()
        project_provider=lambda: [p.project_id for p in pclient.search_projects() if p.state.name=='ACTIVE']
    scope=config.get('project_scope','all')
    if scope!='all':raise ValueError('Only project_scope=all supported in this discovery profile')
    enabled=set(config.get('sources',['bigquery','dataform','scheduled','dbt']))
    result={'schema_version':SCHEMA_VERSION,'snapshot_id':'gcp-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'started_at':utc(),'configuration':{'mode':'lineage','project_scope':scope,'sources':sorted(enabled)},'projects':[],'assets':[],'columns':[],'lineage_edges':[],'repositories':[],'transformations':[],'gaps':[],'source_status':{},'counts':{}}
    try: projects=sorted(set(project_provider()))
    except Exception as exc:
        result['gaps'].append({'source':'projects','status':'ACCESS_DENIED_OR_ERROR','reason':type(exc).__name__})
        projects=[]
    result['projects']=projects
    if 'bigquery' in enabled:
        for project in projects:
            try: datasets=list(client.list_datasets(project=project))
            except Exception as exc:
                result['gaps'].append({'source':'bigquery','project':project,'status':'ACCESS_DENIED_OR_ERROR','reason':type(exc).__name__});continue
            for ds in datasets:
                dsid=ds.dataset_id
                result['assets'].append({'asset_id':asset_id(project,dsid),'platform':'bigquery','asset_type':'dataset','project':project,'dataset':dsid,'name':dsid,'source_uri':f'{project}.{dsid}'})
                try: tables=list(client.list_tables(f'{project}.{dsid}'))
                except Exception as exc:
                    result['gaps'].append({'source':'bigquery','project':project,'dataset':dsid,'status':'ACCESS_DENIED_OR_ERROR','reason':type(exc).__name__});continue
                for t in tables:
                    tid=asset_id(project,dsid,t.table_id)
                    try: detail=client.get_table(f'{project}.{dsid}.{t.table_id}')
                    except Exception as exc:
                        result['gaps'].append({'source':'bigquery','asset_id':tid,'status':'ACCESS_DENIED_OR_ERROR','reason':type(exc).__name__});continue
                    kind=str(getattr(detail,'table_type',getattr(t,'table_type','TABLE')))
                    result['assets'].append({'asset_id':tid,'platform':'bigquery','asset_type':kind,'project':project,'dataset':dsid,'name':t.table_id,'description':getattr(detail,'description',None),'source_uri':f'{project}.{dsid}.{t.table_id}'})
                    def fields(schema,prefix=''):
                        for col in schema:
                            path=prefix+col.name
                            result['columns'].append({'column_id':asset_id(project,dsid,t.table_id,path),'asset_id':tid,'name':col.name,'nested_path':path,'data_type':col.field_type,'nullable':col.mode!='REQUIRED','description':col.description})
                            fields(col.fields,path+'.')
                    fields(detail.schema or [])
                    view_sql=getattr(detail,'view_query',None)
                    if view_sql:
                        result['transformations'].append({'transformation_id':tid,'engine':'bigquery_view','target_asset_id':tid,'sql_sha256':hashlib.sha256(view_sql.encode()).hexdigest(),'sql_stored':False})
                        result['lineage_edges'].extend(classify_sql(view_sql,tid,f'bigquery_view:{tid}'))
        result['source_status']['bigquery']='PARTIAL' if any(g.get('source')=='bigquery' for g in result['gaps']) else 'SUCCESS'
    for source in ('dataform','scheduled'):
        if source not in enabled:continue
        provider={'dataform':dataform_provider,'scheduled':scheduled_provider}[source]
        if provider is None:
            result['source_status'][source]='NOT_CONFIGURED'
            result['gaps'].append({'source':source,'status':'NOT_CONFIGURED','reason':'Discovery adapter not configured; no absence claim'})
        else:
            try:
                items=provider(projects)
                result['repositories'].extend(items if source=='dataform' else [])
                result['source_status'][source]='SUCCESS'
            except Exception as exc:
                result['source_status'][source]='ACCESS_DENIED_OR_ERROR'
                result['gaps'].append({'source':source,'status':'ACCESS_DENIED_OR_ERROR','reason':type(exc).__name__})
    if 'dbt' in enabled:
        manifests=config.get('dbt_manifests',[])
        if not manifests:
            result['source_status']['dbt']='NOT_CONFIGURED'
            result['gaps'].append({'source':'dbt','status':'NOT_CONFIGURED','reason':'dbt manifest paths not registered; cannot discover arbitrary Git repos'})
        else:
            for path in manifests:
                try:
                    m=json.loads(Path(path).read_text(encoding='utf-8'))
                    nodes=m.get('nodes',{});sources=m.get('sources',{})
                    for uid,n in {**sources,**nodes}.items():
                        result['assets'].append({'asset_id':'dbt://'+uid,'platform':'dbt','asset_type':n.get('resource_type','unknown'),'name':n.get('name',uid),'source_uri':str(path)})
                    for uid,n in nodes.items():
                        for parent in n.get('depends_on',{}).get('nodes',[]):
                            result['lineage_edges'].append({'source_id':'dbt://'+parent,'target_id':'dbt://'+uid,'relationship_type':'DEPENDS_ON','evidence_type':'DBT_MANIFEST','confidence':'DECLARED','execution_verified':False,'source_reference':str(path)})
                except Exception as exc:
                    result['gaps'].append({'source':'dbt','status':'ERROR','reason':type(exc).__name__})
            result['source_status']['dbt']='PARTIAL' if any(g['source']=='dbt' for g in result['gaps']) else 'SUCCESS'
    result['counts']={k:len(result[k]) for k in ('projects','assets','columns','lineage_edges','repositories','transformations','gaps')}
    result['completed_at']=utc()
    return result

def export(result,output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('gcp_metadata_manifest.json',json.dumps({k:result[k] for k in ('schema_version','snapshot_id','started_at','completed_at','configuration','counts','source_status')},indent=2))
        for key in ('projects','assets','columns','lineage_edges','repositories','transformations','gaps'):
            z.writestr(f'{key}.json',json.dumps(result[key],indent=2))
    return output

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();cfg=json.loads(Path(a.config).read_text(encoding='utf-8'))
    if cfg.get('mode')!='lineage':p.error('mode must be lineage')
    result=discover(cfg);print(json.dumps({'counts':result['counts'],'source_status':result['source_status']},indent=2));export(result,a.output)
if __name__=='__main__':main()
