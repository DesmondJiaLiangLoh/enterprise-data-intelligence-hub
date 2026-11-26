"""Offline Tableau metadata explorer generator. No network calls or external JS dependencies."""
from pathlib import Path
import zipfile, tempfile, json, csv, io, html, re, hashlib

TABLES=['cloud_workbook','cloud_dashboards','cloud_sheets','cloud_datasources','cloud_datasource_fields','cloud_worksheet_datasource_fields','twb_datasources','twb_fields','twb_calculations','twb_worksheets','twb_dashboards','twb_connections','twb_custom_sql','twb_filters','twb_dashboard_zones','twb_parameters']
SENSITIVE=re.compile(r'password|secret|token|credential|private.key|authorization|username|email|raw_xml|authentication',re.I)
def build_explorer(input_path,output_dir,report_title=None):
    input_path=Path(input_path);out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    def read_zip(z):
        result={}
        for name in TABLES:
            f='csv/'+name+'.csv'
            if f in z.namelist():
                content=z.read(f).decode('utf-8-sig',errors='replace')
                result[name]=[{k:v for k,v in row.items() if not SENSITIVE.search(k)} for row in csv.DictReader(io.StringIO(content))]
            else:result[name]=[]
        manifest=json.loads(z.read('tableau_metadata_run_manifest.json')) if 'tableau_metadata_run_manifest.json' in z.namelist() else {}
        return result,manifest
    if input_path.is_file() and input_path.suffix.lower()=='.zip':
        with zipfile.ZipFile(input_path) as z:tables,manifest=read_zip(z)
    elif input_path.is_dir():
        tables={}
        for name in TABLES:
            f=input_path/'csv'/(name+'.csv')
            tables[name]=[{k:v for k,v in row.items() if not SENSITIVE.search(k)} for row in csv.DictReader(f.open(encoding='utf-8-sig',newline=''))] if f.exists() else []
        m=input_path/'tableau_metadata_run_manifest.json';manifest=json.loads(m.read_text(encoding='utf-8')) if m.exists() else {}
    else:raise ValueError('Input must be a metadata ZIP or extracted directory')
    # Display-only English localization and metadata-backed identifier resolution.
    # Never mutate the original metadata archives or fabricate a translation.
    import unicodedata
    glossary={'参数':'Parameters','复制':'Copy','计算':'Calculation','日期':'Date','开始':'Start','结束':'End','销售':'Sales','数量':'Quantity','金额':'Amount','门店':'Store','商品':'Product','部门':'Department','类别':'Category','供应商':'Vendor','名称':'Name','代码':'Code','总计':'Total','区域':'Region','选择':'Select','全部':'All','年':'Year','月':'Month','日':'Day'}
    non_english=re.compile(r'[^\x00-\x7f]')
    unknown_labels={}
    def english(value):
        if value is None:return ''
        value=str(value)
        for a,b in sorted(glossary.items(),key=lambda x:-len(x[0])):value=value.replace(a,b)
        # Preserve ASCII punctuation and numeric identifiers; mark unsupported labels explicitly.
        if non_english.search(value):
            parts=[]
            for ch in value:
                if ord(ch)<128:parts.append(ch)
                elif ch.isspace():parts.append(' ')
                else:
                    key=f'U+{ord(ch):04X}'
                    unknown_labels[key]=unknown_labels.get(key,0)+1
                    parts.append(' [Untranslated '+key+'] ')
            value=''.join(parts)
        return re.sub(r'\s+',' ',value).strip()
    # A source identifier is an opaque ID, not a business-facing field name.
    field_names={}
    ambiguous=set()
    for row in tables['twb_fields']:
        raw=(row.get('name') or '').strip('[]')
        label=english(row.get('caption') or row.get('name') or raw)
        if not raw or not label:continue
        for key in (raw,'['+raw+']'):
            if key in field_names and field_names[key]!=label:ambiguous.add(key)
            else:field_names[key]=label
    for key in ambiguous:field_names.pop(key,None)
    uuid_token=re.compile(r'(?<![\w-])\[?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]?(?![\w-])',re.I)
    def resolve_formula(formula):
        def repl(m):
            ident=m.group(1)
            return '['+field_names[ident]+']' if ident in field_names else '[Unresolved field '+ident+']'
        return english(uuid_token.sub(repl,str(formula or '')))
    def display_name(row):
        return english(row.get('caption') or row.get('name') or 'Unnamed')
    def clean_record(row):
        result={}
        for k,v in row.items():
            if k=='formula':result[k]=resolve_formula(v)
            elif k in ('name','caption','datasource','field_name','sheet_name','sql','query','text','custom_sql'):
                result[k]=english(v)
            else:result[k]=english(v) if isinstance(v,str) and non_english.search(v) else v
        return result
    # Keep raw extraction out of the browser; all displayed records are English-only.
    tables={k:[clean_record(row) for row in rows] for k,rows in tables.items()}
    field_names={english(k):english(v) for k,v in field_names.items()}
    workbook=manifest.get('selected_workbook') or {}
    title=report_title or (workbook.get('name') if isinstance(workbook,dict) else None) or manifest.get('workbook_name_requested') or input_path.stem
    nodes=[];edges=[];node_ids={};seen_edges=set()
    def add(kind,key,label,detail=None):
        key=str(key or label);ident=kind+':'+key
        if ident not in node_ids:
            node_ids[ident]=len(nodes);nodes.append({'id':ident,'kind':kind,'label':str(label or key),'detail':detail or {}})
        return ident
    def link(a,b,kind='metadata',confidence='verified',reason=''):
        if not a or not b:return
        k=(a,b,kind)
        if k not in seen_edges:seen_edges.add(k);edges.append({'from':a,'to':b,'kind':kind,'confidence':confidence,'reason':reason})
    wb=add('workbook',title,title)
    for row in tables['twb_dashboards']:
        d=add('dashboard',row.get('name'),row.get('caption') or row.get('name'),row);link(d,wb,'contained-in')
    for row in tables['twb_worksheets']:
        s=add('worksheet',row.get('name'),row.get('caption') or row.get('name'),row);link(s,wb,'contained-in')
    for row in tables['twb_datasources']:
        ds=add('datasource',row.get('name'),row.get('caption') or row.get('name'),row);link(ds,wb,'contained-in')
    for row in tables['twb_fields']:
        dsid='datasource:'+str(row.get('datasource'))
        if dsid not in node_ids:continue
        f=add('field',str(row.get('datasource'))+'::'+str(row.get('name')),row.get('caption') or field_names.get(str(row.get('name')).strip('[]')) or row.get('name'),row)
        link(f,dsid,'belongs-to')
    for row in tables['cloud_worksheet_datasource_fields']:
        name=row.get('sheet_name');fname=row.get('field_name')
        if not name or not fname:continue
        s='worksheet:'+str(name)
        if s not in node_ids:continue
        # Source does not guarantee a unique datasource for field name; link to a reference node instead.
        f=add('field-reference',str(name)+'::'+str(row.get('field_id') or fname),field_names.get(str(fname).strip('[]')) or fname,row)
        link(f,s,'used-by','verified','Tableau Metadata API worksheet field association')
    for row in tables['twb_dashboard_zones']:
        d='dashboard:'+str(row.get('dashboard') or row.get('dashboard_name') or row.get('parent_name'))
        s='worksheet:'+str(row.get('name') or row.get('sheet') or row.get('worksheet'))
        if d in node_ids and s in node_ids:link(s,d,'displayed-in')
    for row in tables['twb_connections']:
        ds='datasource:'+str(row.get('datasource'))
        if ds not in node_ids:continue
        parts=[row.get(k,'') for k in ('server','database','schema')]
        if any(parts):
            label=' / '.join(v for v in parts if v)
            conn=add('connection',label,label,row);link(conn,ds,'connects-to','verified')
    formulas=[]
    for row in tables['twb_calculations']:
        if row.get('formula'):
            formulas.append({'name':display_name(row),'formula':resolve_formula(row['formula']),'kind':'Tableau Calculation','source':'twb_calculations'})
    for row in tables['twb_custom_sql']:
        sql=row.get('sql') or row.get('query') or row.get('text') or row.get('custom_sql')
        if sql:formulas.append({'name':row.get('name') or 'Custom SQL','formula':resolve_formula(sql),'kind':'Custom SQL','source':'twb_custom_sql'})
    model={'title':english(title),'nodes':nodes,'edges':edges,'tables':tables,'transformations':formulas,'counts':{k:len(v) for k,v in tables.items()},'manifest':{'workbook':english(title),'extracted_at':manifest.get('extracted_at_utc') or manifest.get('run_id'),'source':'Workflow 3 metadata ZIP'},'limitations':['BigQuery physical schema and SQL repository lineage not connected','ERD reflects extracted Tableau logical associations, not verified physical primary/foreign keys','Missing connection server/database/schema values are shown as unavailable','No custom SQL found' if not tables['twb_custom_sql'] else 'Custom SQL availability depends on extraction']}
    payload=json.dumps(model,ensure_ascii=False).replace('</','<\\/')
    html_template=r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Tableau Metadata Explorer</title><style>
:root{font-family:Segoe UI,Arial,sans-serif;color:#dce7f5;background:#0b1728}*{box-sizing:border-box}body{margin:0}header{padding:19px 28px;background:#11263d;border-bottom:2px solid #18a4a7}header h1{font-size:21px;margin:0 0 5px}header p{margin:0;color:#9db3c7;font-size:12px}.shell{display:grid;grid-template-columns:245px 1fr;min-height:calc(100vh - 84px)}aside{background:#102238;padding:18px;border-right:1px solid #2c4259}aside button{width:100%;background:transparent;color:#cbd9e9;border:0;padding:12px;text-align:left;border-radius:8px;cursor:pointer;margin:3px 0}aside button.active,aside button:hover{background:#147d83;color:white}main{padding:24px;min-width:0}h2{margin:0 0 15px;font-size:20px}h3{font-size:15px;color:#aee9e9}.card{background:#132a41;border:1px solid #28435d;border-radius:10px;padding:17px;margin-bottom:16px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric b{display:block;font-size:27px;color:#60d2d0}input,select{background:#0a1b2c;color:white;border:1px solid #3b5971;border-radius:7px;padding:10px;width:100%}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border-bottom:1px solid #30485f;padding:9px;text-align:left;vertical-align:top;word-break:break-word}th{color:#8bdcda;position:sticky;top:0;background:#132a41}section{display:none}section.active{display:block}.scroll{max-height:490px;overflow:auto}.graph{width:100%;height:470px;background:#091a2b;border:1px solid #35546d;border-radius:9px;overflow:auto}svg{width:100%;height:100%;min-width:850px}svg text{fill:white;font-size:11px;pointer-events:none}svg .node{cursor:pointer}svg .node rect{stroke:#6e9aaf;stroke-width:1}svg .node:hover rect,svg .node.focus rect{stroke:#fff;stroke-width:3;filter:drop-shadow(0 0 7px #56d9d4)}svg .edge.focus{stroke:#64e6df;stroke-width:3;opacity:1}svg .node.dim,svg .edge.dim{opacity:.12}svg .node.selected rect{stroke:#f6d365;stroke-width:4;filter:drop-shadow(0 0 9px #f6d365)}svg .node:focus{outline:none}svg .node:focus rect{stroke:#f6d365;stroke-width:3}.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:12px}.toolbar input{max-width:430px}.toolbar select{max-width:190px}pre{white-space:pre-wrap;word-break:break-word;background:#091a2b;border:1px solid #2d4b62;padding:16px;border-radius:8px;color:#aee9e9;max-height:440px;overflow:auto}.muted{color:#a9bed1;font-size:12px}.chip{display:inline-block;border:1px solid #397c85;border-radius:20px;padding:4px 10px;margin:4px;color:#8ce2de;font-size:11px}.notice{border-left:3px solid #e5aa54;padding:9px 13px;background:#302d2d;margin-bottom:12px;font-size:12px}@media(max-width:850px){.shell{display:block}aside{display:flex;flex-wrap:wrap}aside button{width:auto}.metrics{grid-template-columns:repeat(2,1fr)}main{padding:14px}}</style></head><body>
<header><h1>Tableau Metadata Intelligence Explorer</h1><p id="subtitle"></p></header><div class="shell"><aside><button class="active" data-tab="overview">◈ Overview & Discovery</button><button data-tab="lineage">◇ Metadata Lineage</button><button data-tab="mapping">▤ Data Mapping / ERD</button><button data-tab="logic">⌘ Transformation Logic</button><button data-tab="inventory">▦ Source Metadata Inventory</button><button data-tab="quality">⚑ Evidence & Gaps</button></aside><main>
<section id="overview" class="active"><h2>Metadata Discovery</h2><div class="metrics" id="metrics"></div><div class="card"><h3>Search extracted objects</h3><input id="find" placeholder="Search workbook, dashboards, worksheets, fields, data sources..."/><div class="scroll"><table><thead><tr><th>Type</th><th>Object</th><th>Source identifier</th></tr></thead><tbody id="searchResults"></tbody></table></div></div></section>
<section id="lineage"><h2>Metadata Discovery & Lineage</h2><p class="muted">Arrows point from upstream/contained objects toward downstream consumers. Select nodes to inspect provenance. The graph is a documented subset, not a complete BigQuery lineage.</p><div class="toolbar"><select id="graphKind"><option value="all">All object types</option><option value="worksheet">Worksheets</option><option value="datasource">Data sources</option><option value="dashboard">Dashboards</option></select><input id="graphSearch" placeholder="Find node by name"/></div><div class="graph"><svg id="lineageSvg" viewBox="0 0 1000 500"></svg></div><div class="card" id="nodeDetails">Select a node to view metadata.</div></section>
<section id="mapping"><h2>Visual Data Mapping & ERD-style View</h2><div class="notice">Relationships here are metadata associations. Physical database PK/FK constraints and cardinality are not asserted unless independently verified.</div><div class="toolbar"><select id="dsSelect"></select></div><div class="card" id="dsDetails"></div><div class="card"><h3>Fields in selected data source</h3><div class="scroll" id="fieldTable"></div></div></section>
<section id="logic"><h2>Transformation Logic</h2><p class="muted">Original Tableau calculation formulas and available custom SQL. BigQuery SQL, dbt and Dataform source code require future connectors.</p><div class="toolbar"><input id="logicSearch" placeholder="Search calculation names or formulas"/></div><div class="card" id="logicList"></div></section>
<section id="inventory"><h2>Source Metadata Inventory</h2><div class="toolbar"><select id="tableSelect"></select><input id="tableSearch" placeholder="Search records"/></div><div class="card scroll" id="tableResults"></div></section>
<section id="quality"><h2>Provenance, Completeness & Limitations</h2><div id="limitations"></div><div class="card"><h3>Extracted table counts</h3><div id="tableCounts"></div></div></section>
</main></div><script id="data" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent);document.getElementById('subtitle').textContent=D.title+'  |  Offline snapshot from Workflow 3  |  No live BigQuery connection';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fieldLookup=Object.fromEntries(D.tables.twb_fields.filter(f=>f.caption).map(f=>[String(f.name).replace(/^\[|\]$/g,''),f.caption]));const fieldLabel=(name,caption)=>caption||fieldLookup[String(name||'').replace(/^\[|\]$/g,'')]||name;
const cap=s=>s.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
function show(tab){document.querySelectorAll('section').forEach(x=>x.classList.toggle('active',x.id===tab));document.querySelectorAll('aside button').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));if(tab==='lineage')drawGraph();}
document.querySelectorAll('aside button').forEach(b=>b.onclick=()=>show(b.dataset.tab));
const counts=[['Dashboards',D.tables.twb_dashboards.length],['Worksheets',D.tables.twb_worksheets.length],['Data Sources',D.tables.twb_datasources.length],['Calculated Fields',D.transformations.filter(x=>x.kind==='Tableau Calculation').length]];
document.getElementById('metrics').innerHTML=counts.map(([k,v])=>`<div class="card metric"><b>${v}</b>${k}</div>`).join('');
function searchNodes(){let q=document.getElementById('find').value.toLowerCase();document.getElementById('searchResults').innerHTML=D.nodes.filter(x=>x.label.toLowerCase().includes(q)||x.kind.includes(q)).slice(0,350).map(x=>`<tr><td>${esc(cap(x.kind))}</td><td>${esc(x.label)}</td><td>${esc(x.kind==='field' ? (x.label+' (Tableau field)') : x.kind==='field-reference' ? (x.label+' (worksheet field)') : x.label)}</td></tr>`).join('')||'<tr><td colspan="3">No matching objects</td></tr>';}document.getElementById('find').oninput=searchNodes;searchNodes();
const kinds={workbook:'#19a3a6',dashboard:'#2d8bbd',worksheet:'#4e72a9',datasource:'#9669b0',field:'#526b80','field-reference':'#526b80',connection:'#d08b55'};
let pinnedLineageId=null;
function drawGraph(){
 const svg=document.getElementById('lineageSvg');
 const kind=document.getElementById('graphKind').value,q=document.getElementById('graphSearch').value.toLowerCase();
 const focus=D.nodes.filter(x=>(kind==='all'?['workbook','dashboard','worksheet','datasource','connection'].includes(x.kind):x.kind===kind)&&(!q||x.label.toLowerCase().includes(q))).slice(0,75);
 const visible=new Set(focus.map(x=>x.id));
 const edges=D.edges.filter(e=>visible.has(e.from)&&visible.has(e.to));
 const h=Math.max(450,Math.ceil(focus.length/4)*95+70);
 svg.setAttribute('viewBox',`0 0 1000 ${h}`);svg.style.height=h+'px';
 const positions={};focus.forEach((n,i)=>positions[n.id]={x:20+(i%4)*245,y:45+Math.floor(i/4)*95});
 let html=`<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0 0 L7 3 L0 6" fill="none" stroke="#6ca8b6"/></marker></defs>`;
 edges.forEach(e=>{const a=positions[e.from],b=positions[e.to];html+=`<path class="edge" data-from="${esc(e.from)}" data-to="${esc(e.to)}" d="M${a.x+195} ${a.y+20} L${b.x} ${b.y+20}" stroke="#6ca8b6" opacity=".65" fill="none" marker-end="url(#arrow)"/>`;});
 focus.forEach(n=>{const p=positions[n.id];html+=`<g class="node" data-id="${esc(n.id)}" tabindex="0" role="button" aria-label="Select ${esc(n.label)}"><rect x="${p.x}" y="${p.y}" width="195" height="45" rx="7" fill="${kinds[n.kind]||'#607080'}"/><text x="${p.x+9}" y="${p.y+17}">${esc(n.kind)}</text><text x="${p.x+9}" y="${p.y+33}">${esc(n.label.slice(0,29))}</text><title>${esc(n.label)} — ${esc(n.kind)}. Click to pin linked metadata; click again to clear.</title></g>`;});
 svg.innerHTML=html;
 function highlight(id){
  const related=new Set([id]);
  edges.forEach(e=>{if(e.from===id)related.add(e.to);if(e.to===id)related.add(e.from)});
  svg.querySelectorAll('g.node').forEach(n=>{const hit=related.has(n.dataset.id);n.classList.toggle('focus',hit);n.classList.toggle('dim',!hit);n.classList.toggle('selected',n.dataset.id===id);});
  svg.querySelectorAll('path.edge').forEach(e=>{const hit=e.dataset.from===id||e.dataset.to===id;e.classList.toggle('focus',hit);e.classList.toggle('dim',!hit);});
 }
 function clear(){svg.querySelectorAll('.node,.edge').forEach(x=>x.classList.remove('focus','dim','selected'));}
 function detail(id){const n=D.nodes.find(x=>x.id===id);if(!n)return;const relations=D.edges.filter(e=>e.from===n.id||e.to===n.id);document.getElementById('nodeDetails').innerHTML=`<h3>${esc(n.label)} — Selected lineage</h3><p class="muted">${esc(n.kind)} | ${relations.length} recorded direct relationships. Click this node again to reset.</p><pre>${esc(JSON.stringify(n.detail,null,2))}</pre><ul>${relations.slice(0,35).map(e=>{const other=D.nodes.find(x=>x.id===(e.from===n.id?e.to:e.from));return '<li>'+esc(other?.label||'Unknown')+' — '+esc(e.kind)+' ('+esc(e.confidence)+')</li>'}).join('')}</ul>`;}
 svg.querySelectorAll('g.node').forEach(node=>{
  const id=node.dataset.id;
  node.addEventListener('mouseenter',()=>{if(!pinnedLineageId)highlight(id)});
  node.addEventListener('mouseleave',()=>{if(pinnedLineageId)highlight(pinnedLineageId);else clear()});
  const select=()=>{if(pinnedLineageId===id){pinnedLineageId=null;clear();document.getElementById('nodeDetails').textContent='Selection cleared. Click a node to pin its linked metadata.';}else{pinnedLineageId=id;highlight(id);detail(id)}};
  node.addEventListener('click',select);
  node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select()}});
 });
 if(pinnedLineageId&&visible.has(pinnedLineageId)){highlight(pinnedLineageId);detail(pinnedLineageId)}else if(pinnedLineageId){pinnedLineageId=null;}
}
document.getElementById('graphKind').onchange=drawGraph;document.getElementById('graphSearch').oninput=drawGraph;
let ds=D.tables.twb_datasources;let select=document.getElementById('dsSelect');select.innerHTML=ds.map((x,i)=>`<option value="${i}">${esc(x.caption||x.name)}</option>`).join('');function dsRender(){let d=ds[+select.value];if(!d){document.getElementById('dsDetails').textContent='No Tableau data sources available';return;}document.getElementById('dsDetails').innerHTML=`<h3>${esc(d.caption||d.name)}</h3><p class="muted">Tableau data source: ${esc(d.caption||d.name)}</p>`;let rows=D.tables.twb_fields.filter(f=>f.datasource===d.name);document.getElementById('fieldTable').innerHTML=`<table><thead><tr><th>Logical field</th><th>Physical/internal name</th><th>Data type</th><th>Role</th></tr></thead><tbody>${rows.map(f=>`<tr><td>${esc(f.caption||f.name)}</td><td>${esc(fieldLabel(f.name,f.caption))}</td><td>${esc(f.datatype)}</td><td>${esc(f.role)}</td></tr>`).join('')}</tbody></table>`;}select.onchange=dsRender;dsRender();
function logicRender(){let q=document.getElementById('logicSearch').value.toLowerCase(),items=D.transformations.filter(x=>(x.name+' '+x.formula).toLowerCase().includes(q)).slice(0,200);document.getElementById('logicList').innerHTML=items.length?items.map(x=>`<details><summary>${esc(x.name)} <span class="chip">${esc(x.kind)}</span></summary><pre>${esc(x.formula)}</pre><p class="muted">Source: ${esc(x.source)}</p></details>`).join(''):'<p>No matching transformation records. BigQuery SQL / dbt / Dataform not connected.</p>';}document.getElementById('logicSearch').oninput=logicRender;logicRender();
let keys=Object.keys(D.tables);let tsel=document.getElementById('tableSelect');tsel.innerHTML=keys.map(x=>`<option>${esc(x)}</option>`).join('');function tableRender(){let rows=D.tables[tsel.value]||[],q=document.getElementById('tableSearch').value.toLowerCase();rows=rows.filter(x=>JSON.stringify(x).toLowerCase().includes(q)).slice(0,250);let columns=Array.from(new Set(rows.flatMap(Object.keys))).slice(0,14);document.getElementById('tableResults').innerHTML=`<p class="muted">Showing up to 250 matching records; source rows are preserved in the embedded metadata snapshot.</p><table><thead><tr>${columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${columns.map(c=>`<td>${esc(String((c==='name'||c==='field_name')?fieldLabel(r[c],r.caption):r[c]||'').slice(0,350))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;}tsel.onchange=tableRender;document.getElementById('tableSearch').oninput=tableRender;tableRender();
document.getElementById('limitations').innerHTML=D.limitations.map(x=>`<div class="notice">${esc(x)}</div>`).join('');document.getElementById('tableCounts').innerHTML=Object.entries(D.counts).map(([k,v])=>`<span class="chip">${esc(k)}: ${v}</span>`).join('');
</script></body></html>'''
    target=out/(re.sub(r'[^\w.-]+','_',title).strip('_')[:90]+'_Metadata_Explorer.html')
    target.write_text(html_template.replace('__DATA__',payload),encoding='utf-8')
    return str(target)
