import json,re
from pathlib import Path
from xml.etree import ElementTree as ET
CATALOG=[dict(name='Retail performance',tags='sales revenue store retail dashboard',views=140),dict(name='Product profitability',tags='margin cost product profit sales',views=95),dict(name='Inventory health',tags='stock replenishment inventory store',views=75)]
def match(query):
    tokens=set(re.findall(r'\w+',query.lower())); return sorted([dict(a,score=len(tokens & set(a['tags'].split()))) for a in CATALOG if tokens & set(a['tags'].split())],key=lambda a:(-a['score'],-a['views'],a['name']))
def extract(path):
    tree=ET.parse(path).getroot(); nodes=[]; edges=[]
    for el in tree:
        nodes.append(dict(id=el.attrib['id'],type=el.tag,label=el.attrib['name']))
        for dep in el.attrib.get('depends','').split(): edges.append(dict(source=dep,target=el.attrib['id']))
    ids={n['id'] for n in nodes}
    if len(ids)!=len(nodes) or any(e['source'] not in ids for e in edges): raise ValueError('Invalid metadata graph')
    return dict(nodes=nodes,edges=edges)
def run():
    graph=extract(Path(__file__).parent/'fictional.xml'); return dict(scope='Fictional catalog and simplified XML schema; not Tableau API execution',WF1=match('retail sales'),WF2=match('product margin'),WF3=graph)
if __name__=='__main__':
    p=Path(__file__).parent; result=run(); (p/'results.json').write_text(json.dumps(result,indent=2)); (p/'generated-documentation.md').write_text('# Fictional workbook documentation\n\n'+'\n'.join('- '+n['type']+': '+n['label'] for n in result['WF3']['nodes'])+'\n\n## Dependencies\n'+'\n'.join('- '+e['source']+' → '+e['target'] for e in result['WF3']['edges']))
