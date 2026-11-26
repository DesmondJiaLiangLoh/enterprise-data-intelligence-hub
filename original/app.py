from flask import Flask,request,jsonify,send_from_directory,render_template_string,abort
from pathlib import Path
from datetime import datetime,timezone
import subprocess,sys,os,json,uuid,threading,re,zipfile,hashlib,signal,shutil
from flask import Response, redirect, url_for

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'runs';RUNS.mkdir(exist_ok=True)
app=Flask(__name__)
# Ephemeral signing key is intentional for local development: restart invalidates sessions.
app.secret_key=os.environ.get('PORTAL_SESSION_SECRET') or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=False)
from gcp_oauth import bp as gcp_auth_blueprint, credentials as gcp_user_credentials
app.register_blueprint(gcp_auth_blueprint)
EXPLORER_CACHE=ROOT/'explorer_cache';EXPLORER_CACHE.mkdir(exist_ok=True)

CATALOG={
'p1':{'title':'Initiative Asset Intelligence','description':'Discover Tableau projects and assets for a domain or initiative. Produce a navigable inventory and activity-prioritization outputs.','fields':[('project_search','Project / domain keyword','text','Commercial Finance'),('include_descendant_projects','Include child projects','bool',True),('dry_run','Discovery only (dry run)','bool',False),('query_metadata_api','Query Metadata API','bool',False),('max_assets_per_type','Maximum assets per type (blank = all)','int','')]},
'p2':{'title':'Operational Task Asset Intelligence','description':'Match Scrum initiative titles and descriptions against Tableau workbooks, data sources and flows.','fields':[('target_sheet','Scrum worksheet','text','Pipeline 2026 Q4'),('minimum_potential_score','Minimum match score','int',35),('top_matches_per_asset_type','Matches per asset type','int',5),('include_all_projects','Search all projects','bool',True)]},
'p3':{'title':'Metadata & Lineage Intelligence','description':'Extract Tableau metadata, generate Word documentation, and explore lineage, mappings and transformations in the integrated Metadata Explorer.','fields':[('workbook_name','Workbook name','text','Retail Performance Demo'),('workbook_luid','Workbook LUID (optional)','text',''),('project_path','Project hierarchy (separate with /)','path','Demo / Analytics / Retail'),('query_metadata_api','Query Metadata API','bool',True),('download_workbook','Download workbook','bool',True),('capture_view_screenshots','Capture view screenshots','bool',True),('mode','Mode: cloud or local','text','cloud'),('local_workbook','Local workbook path (local mode)','text',''),('generate_documentation','Generate Word documentation after extraction','bool',True)]}}


@app.get('/')
def index():return render_template_string((ROOT/'templates'/'index.html').read_text(encoding='utf-8'))
@app.get('/api/catalog')
def catalog():return jsonify(CATALOG)

ACTIVE_PROCESSES = {}
ACTIVE_GCP_CANCEL = {}
RUN_LOCK = threading.RLock()

def _read_status(folder):
    return json.loads((folder/'status.json').read_text(encoding='utf-8'))

def _finish_run(folder, status, code):
    with RUN_LOCK:
        current=_read_status(folder)
        if current.get('status') in ('terminated','completed','failed'):
            return
        current.update(status=status, exit_code=code, finished=datetime.now(timezone.utc).isoformat())
        (folder/'status.json').write_text(json.dumps(current),encoding='utf-8')

def execute(run_id,job,env):
    folder=RUNS/run_id
    try:
        with (folder/'console.log').open('w',encoding='utf-8',errors='replace') as log:
            flags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
            proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'hub_runner.py'),str(job)],cwd=str(folder),stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=flags,start_new_session=(os.name!='nt'))
            with RUN_LOCK:
                ACTIVE_PROCESSES[run_id]=proc
                (folder/'pid').write_text(str(proc.pid))
                if _read_status(folder).get('status')=='terminated':
                    _kill_tree(proc)
            code=proc.wait()
        _finish_run(folder,'completed' if code==0 else 'failed',code)
    except Exception as exc:
        (folder/'console.log').open('a',encoding='utf-8').write('Execution error: '+str(exc)+'\n')
        _finish_run(folder,'failed',1)
    finally:
        with RUN_LOCK: ACTIVE_PROCESSES.pop(run_id,None)

def _kill_tree(proc):
    if proc.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=15,check=False)
    else:
        try:os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:pass

def _zip_fingerprint(path):
    # Full content hash collapses copies from metadata folder and run output.
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

@app.get('/api/metadata-workbooks')
def metadata_workbooks():
    folder = ROOT / 'inputs' / 'metadata'
    result = []
    if folder.is_dir():
        for path in sorted(folder.glob('*.zip'), key=lambda p:p.stat().st_mtime, reverse=True):
            try:
                with __import__('zipfile').ZipFile(path) as z:
                    if z.testzip() is not None or 'tableau_metadata_run_manifest.json' not in z.namelist():
                        continue
                    manifest = json.loads(z.read('tableau_metadata_run_manifest.json'))
                    name = manifest.get('workbook_name_requested') or path.stem.replace('_',' ')
                    selected = manifest.get('selected_workbook') or {}
                    if isinstance(selected,dict): name = selected.get('name') or name
                    result.append({'name':name,'file':path.name,'status':manifest.get('status')})
            except (OSError, ValueError, KeyError, __import__('zipfile').BadZipFile):
                continue
    return jsonify(result)

def explorer_sources():
    """Allowlisted metadata archives: Workflow 3 packages and completed run outputs."""
    items=[]
    folder=ROOT/'inputs'/'metadata'
    candidates=[]
    if folder.is_dir():candidates.extend(('metadata',p) for p in folder.glob('*.zip'))
    if RUNS.is_dir():
        for run in RUNS.iterdir():
            if not run.is_dir() or not re.fullmatch(r'[0-9TZ]+_[a-f0-9]{8}',run.name):continue
            candidates.extend((run.name,p) for p in (run/'outputs').glob('*.zip'))
    for scope,path in candidates:
        try:
            if path.stat().st_size>200*1024*1024:continue
            with zipfile.ZipFile(path) as z:
                names=set(z.namelist())
                if 'tableau_metadata_run_manifest.json' not in names:continue
                if not any(n.startswith('csv/') and n.endswith('.csv') for n in names):continue
                if sum(i.file_size for i in z.infolist())>700*1024*1024:continue
                m=json.loads(z.read('tableau_metadata_run_manifest.json'))
            selected=m.get('selected_workbook') or {}
            title=(selected.get('name') if isinstance(selected,dict) else None) or m.get('workbook_name_requested') or path.stem
            key=_zip_fingerprint(path)[:24]
            from datetime import datetime, timezone
            stamp=m.get('run_finished_utc') or m.get('extracted_at_utc') or m.get('completed_at_utc') or m.get('run_started_utc') or m.get('started_at_utc')
            if not stamp:
                stamp=next((r.get('extracted_at_utc') for r in [m.get('metadata',{})] if isinstance(r,dict) and r.get('extracted_at_utc')),None)
            try:
                dt=datetime.fromisoformat(str(stamp).replace('Z','+00:00')) if stamp else None
                if dt and dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
                ts=dt.timestamp() if dt else path.stat().st_mtime
                basis='Extraction' if dt else 'File modified'
            except (ValueError,OverflowError,TypeError):
                ts=path.stat().st_mtime;basis='File modified'
            display=datetime.fromtimestamp(ts,timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            items.append({'id':key,'name':title,'filename':path.name,'source':'Workflow 3 metadata' if scope=='metadata' else 'Run '+scope,'path':path,'modified':ts,'last_modified':display,'date_basis':basis,'scope':scope})
        except (OSError,ValueError,zipfile.BadZipFile,KeyError):continue
    merged={}
    for item in items:
        existing=merged.get(item['id'])
        if existing is None:
            item['sources']=[item['source']]
            merged[item['id']]=item
        else:
            if item['source'] not in existing['sources']:existing['sources'].append(item['source'])
            # Prefer canonical metadata copy, then latest run copy.
            if item['scope']=='metadata' and existing['scope']!='metadata':
                existing['path']=item['path'];existing['filename']=item['filename']
            if item['modified']>existing['modified']:
                existing['modified']=item['modified'];existing['last_modified']=item['last_modified'];existing['date_basis']=item['date_basis']
    return sorted(merged.values(),key=lambda x:x['modified'],reverse=True)

@app.get('/api/workflow3/explorer/sources')
def explorer_list():
    return jsonify([{k:v for k,v in item.items() if k not in ('path','modified','scope')} for item in explorer_sources()])

@app.get('/workflow3/explorer')
def explorer_page():
    return render_template_string((ROOT/'templates'/'explorer.html').read_text(encoding='utf-8'))

@app.get('/workflow3/explorer/view/<source_id>')
def explorer_view(source_id):
    item=next((x for x in explorer_sources() if x['id']==source_id),None)
    if item is None:abort(404)
    from visual_explorer import build_explorer
    path=item['path'];fingerprint=hashlib.sha256((str(path.resolve())+str(path.stat().st_size)+str(path.stat().st_mtime_ns)+'|explorer-v3-js-fixed').encode()).hexdigest()[:24]
    cache=EXPLORER_CACHE/fingerprint
    target=cache/(path.stem+'_Metadata_Explorer.html')
    if not target.exists():
        cache.mkdir(parents=True,exist_ok=True)
        result=Path(build_explorer(path,cache,report_title=item['name']))
        if result!=target:target=result
    response=Response(target.read_text(encoding='utf-8'),mimetype='text/html')
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    return response

@app.post('/api/run')
def start():
    data=request.get_json(silent=True) or {};key=data.get('pipeline')
    if key not in CATALOG:return jsonify(error='Unknown pipeline'),400
    raw=data.get('parameters') or {};allowed={f[0]:f for f in CATALOG[key]['fields']}
    params={}
    for k,v in raw.items():
        if k not in allowed:return jsonify(error='Unsupported parameter: '+k),400
        typ=allowed[k][2]
        if typ=='bool':v=(v is True)
        elif typ=='int':
            if v in ('',None):v=None
            else:
                try:v=int(v)
                except (ValueError,TypeError):return jsonify(error='Invalid integer for '+k),400
        elif typ=='workbook':v=str(v).strip()
        elif typ=='path':v=[s.strip() for s in (v if isinstance(v,list) else str(v).split('/')) if s.strip()]
        else:v=str(v).strip()
        if v is not None and v != '' and v != []:
            params[k]=v
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    folder=RUNS/run_id;folder.mkdir()
    params['output_dir']=str(folder/'outputs')
    if key=='p1':params['inventory_filename']='Tableau_Project_Inventory.xlsx'
    if key=='p2':
        params['input_xlsx']=str(ROOT/'inputs'/'CF Scrum Pipeline.xlsx')
        params['output_xlsx']=str(folder/'outputs'/'Scrum_Tableau_Asset_Matches.xlsx')
    if key=='p3':
        params['download_dir']=str(folder/'working')
        params['output_dir']=str(folder/'outputs')
    (folder/'outputs').mkdir(exist_ok=True)
    env=os.environ.copy()
    if key in ('p1','p2') or (key=='p3' and params.get('mode','cloud').lower()!='local'):
        pat=data.get('pat_name','').strip();secret=data.get('pat_secret','')
        if not pat or not secret:return jsonify(error='PAT name and secret are required'),400
        env['TABLEAU_PAT_NAME']=pat;env['TABLEAU_PAT_SECRET']=secret
    # Credentials are only passed via process environment, never written to disk.
    job=folder/'job.json';job.write_text(json.dumps({'pipeline':key,'parameters':params},indent=2))
    (folder/'status.json').write_text(json.dumps({'status':'running','started':datetime.now(timezone.utc).isoformat(),'pipeline':key,'criteria':{k:v for k,v in params.items() if k not in ('output_dir','download_dir','input_xlsx','output_xlsx','inventory_filename') and (k in ('project_search','target_sheet','workbook_name','project_path','local_workbook','workbook_luid'))}}))
    threading.Thread(target=execute,args=(run_id,job,env),daemon=True).start()
    return jsonify(run_id=run_id,status='running')

@app.post('/api/runs/<run_id>/terminate')
def terminate_run(run_id):
    if not re.fullmatch(r'[0-9TZ]+_[a-f0-9]{8}',run_id):abort(404)
    # Reject cross-origin browser requests to the localhost control endpoint.
    origin=request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
        return jsonify(error='Cross-origin termination is not permitted'),403
    folder=RUNS/run_id
    if not (folder/'status.json').exists():abort(404)
    with RUN_LOCK:
        status=_read_status(folder)
        if status.get('status')!='running':
            return jsonify(error='Execution is not running',status=status.get('status')),409
        proc=ACTIVE_PROCESSES.get(run_id)
        cancel=ACTIVE_GCP_CANCEL.get(run_id)
        if proc is None and cancel is None:
            return jsonify(error='No active worker registered. Restarted or orphaned executions cannot be terminated safely from this session.'),409
        if cancel is not None:cancel.set()
        status.update(status='terminated',finished=datetime.now(timezone.utc).isoformat(),exit_code=-15)
        (folder/'status.json').write_text(json.dumps(status),encoding='utf-8')
    if proc is not None:
        try:_kill_tree(proc)
        except Exception as exc:return jsonify(status='terminated',warning='Termination requested; process stop could not be confirmed: '+str(exc)),202
    with (folder/'console.log').open('a',encoding='utf-8') as log:
        log.write('\nTermination requested by Portal user.\n')
    return jsonify(status='terminated',run_id=run_id,detail='Termination requested')

@app.get('/api/runs/latest')
def latest_runs():
    """Return latest run for each workflow, persisted on disk across server restarts."""
    latest={}
    for folder in sorted(RUNS.iterdir(),key=lambda x:x.name,reverse=True):
        if not folder.is_dir():continue
        status_path=folder/'status.json'
        if not status_path.exists():continue
        try:
            data=json.loads(status_path.read_text(encoding='utf-8'))
            key=data.get('pipeline')
            if not key:
                job=folder/'job.json'
                if job.exists():key=json.loads(job.read_text(encoding='utf-8')).get('pipeline')
            if key not in CATALOG or key in latest:continue
            if 'criteria' not in data:
                job=folder/'job.json'
                if job.exists():
                    params=json.loads(job.read_text(encoding='utf-8')).get('parameters',{})
                    data['criteria']={k:params[k] for k in ('project_search','target_sheet','workbook_name','project_path','local_workbook','workbook_luid') if params.get(k)}
            data['run_id']=folder.name
            latest[key]=data
            if len(latest)==len(CATALOG):break
        except (ValueError,OSError,KeyError):continue
    return jsonify(latest)

@app.get('/api/runs/<run_id>')
def status(run_id):
    if not re.fullmatch(r'[0-9TZ]+_[a-f0-9]{8}',run_id):abort(404)
    folder=RUNS/run_id
    if not folder.exists():abort(404)
    status=json.loads((folder/'status.json').read_text())
    log=(folder/'console.log').read_text(encoding='utf-8',errors='replace')[-25000:] if (folder/'console.log').exists() else ''
    outputs=[str(p.relative_to(folder/'outputs')) for p in (folder/'outputs').rglob('*') if p.is_file() and len(p.relative_to(folder/'outputs').parts)<=5]
    return jsonify(**status,log=log,outputs=outputs[:150])

@app.get('/api/runs/<run_id>/files/<path:filename>')
def download(run_id,filename):
    if not re.fullmatch(r'[0-9TZ]+_[a-f0-9]{8}',run_id):abort(404)
    return send_from_directory(RUNS/run_id/'outputs',filename,as_attachment=True)


# GCP discovery uses session-only OAuth credentials; no ADC or token files.
@app.get('/workflow3/gcp')
def gcp_page():
    return render_template_string((ROOT/'templates'/'gcp.html').read_text(encoding='utf-8'))

@app.get('/api/workflow3/gcp/preflight')
def gcp_preflight():
    """Read-only permission diagnostics; never query business rows."""
    creds=gcp_user_credentials()
    if creds is None:return jsonify(status='AUTH_REQUIRED', checks=[]),401
    checks=[]
    billing=os.environ.get('GCP_METADATA_BILLING_PROJECT') or os.environ.get('GOOGLE_CLOUD_PROJECT')
    if not billing:
        checks.append({'name':'Query/quota project','status':'CONFIG_REQUIRED','detail':'Set GCP_METADATA_BILLING_PROJECT to an approved project ID.'})
    else:
        checks.append({'name':'Query/quota project','status':'CONFIGURED','detail':billing})
    try:
        from google.cloud import resourcemanager_v3
        pc=resourcemanager_v3.ProjectsClient(credentials=creds)
        projects=[x.project_id for x in pc.search_projects() if getattr(x.state,'name',None)=='ACTIVE']
        checks.append({'name':'Project discovery','status':'PASS','detail':f'{len(projects)} active visible project(s)', 'count':len(projects)})
    except Exception as exc:
        checks.append({'name':'Project discovery','status':'ERROR','detail':f'{type(exc).__name__}: {str(exc)[:220]}'})
    if billing:
        try:
            from google.cloud import bigquery
            client=bigquery.Client(project=billing,credentials=creds)
            next(iter(client.list_datasets(project=billing,max_results=1)),None)
            checks.append({'name':'BigQuery metadata access','status':'PASS','detail':'Dataset listing succeeded for query project'})
        except Exception as exc:
            checks.append({'name':'BigQuery metadata access','status':'ERROR','detail':f'{type(exc).__name__}: {str(exc)[:220]}'})
    return jsonify(status='READY' if all(c['status'] in ('PASS','CONFIGURED') for c in checks) else 'ATTENTION', checks=checks)

@app.post('/api/workflow3/gcp/discover')
def gcp_discover():
    user_creds=gcp_user_credentials()
    if user_creds is None:return jsonify(error='Sign in with corporate Google from Workflow 3 before discovery.'),401
    data=request.get_json(silent=True) or {}
    if data.get('confirm_read_only') is not True:
        return jsonify(error='Explicit read-only discovery confirmation required'),400
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    folder=RUNS/run_id;folder.mkdir();(folder/'outputs').mkdir()
    config={'mode':'lineage','project_scope':'all','sources':['bigquery','dataform','scheduled','dbt'], 'billing_project':os.environ.get('GCP_METADATA_BILLING_PROJECT','')}
    (folder/'gcp_config.json').write_text(json.dumps(config))
    (folder/'status.json').write_text(json.dumps({'status':'running','started':datetime.now(timezone.utc).isoformat(),'pipeline':'gcp','criteria':{'mode':'lineage','project_scope':'all'}}))
    cancel_event=threading.Event()
    with RUN_LOCK:ACTIVE_GCP_CANCEL[run_id]=cancel_event
    def work(creds=user_creds):
        with (folder/'console.log').open('w',encoding='utf-8') as log:
            try:
                from google.cloud import bigquery, resourcemanager_v3
                from gcp_connector import discover, export
                billing=config.get('billing_project') or os.environ.get('GOOGLE_CLOUD_PROJECT')
                if not billing:
                    raise RuntimeError('Set GCP_METADATA_BILLING_PROJECT to an approved query/quota project.')
                client=bigquery.Client(project=billing,credentials=creds)
                project_client=resourcemanager_v3.ProjectsClient(credentials=creds)
                provider=lambda: [p.project_id for p in project_client.search_projects() if p.state.name=='ACTIVE']
                if cancel_event.is_set():raise InterruptedError("GCP discovery terminated")
                result=discover(config,client=client,project_provider=provider)
                if cancel_event.is_set():raise InterruptedError("GCP discovery terminated")
                export(result,folder/'outputs'/'GCP_Metadata_Discovery.zip')
                log.write(json.dumps({'counts':result['counts'],'source_status':result['source_status']},indent=2))
                code=0
            except Exception as exc:
                log.write(f'Connector failed: {type(exc).__name__}: {str(exc)[:350]}\n')
                code=1
        _finish_run(folder,'completed' if code==0 else 'failed',code)
        with RUN_LOCK:ACTIVE_GCP_CANCEL.pop(run_id,None)
    threading.Thread(target=work,daemon=True).start()
    return jsonify(run_id=run_id,status='running')

if __name__=='__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=False)
