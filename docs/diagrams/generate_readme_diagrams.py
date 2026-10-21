"""从同一份简版规格生成 SVG、Mermaid 和文档索引。"""
from pathlib import Path
from html import escape
import importlib.util
import json
import os
import re
import sys
from PIL import ImageFont
from readme_specs import DIAGRAMS

ROOT=Path(os.environ.get('DIAGRAM_OUTPUT_ROOT',Path(__file__).resolve().parent))
SKILL=Path(os.environ.get('FIREWORKS_SKILL_ROOT',Path.home()/'.agents/skills/fireworks-tech-graph'))
sys.path.insert(0,str(SKILL/'scripts'))
from validate_svg import run_check

FONT=Path('C:/Windows/Fonts/msyh.ttc')
if not FONT.exists():
    FONT=Path(os.environ.get('DIAGRAM_FONT','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
FONTS={}
def length(s,size):
    if size not in FONTS:FONTS[size]=ImageFont.truetype(str(FONT),size)
    return FONTS[size].getlength(s)


def text(x,y,s,size=24,weight=400,color='#111827',anchor='middle'):
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(s)}</text>'


def render(d):
    p=[];w,h=d['width'],d['height']
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" data-generator="fireworks-tech-graph" data-style="4" data-quality-profile="showcase" role="img" aria-labelledby="diagram-title diagram-desc">')
    p.extend([f'<title id="diagram-title">{escape(d["title"])}</title>',f'<desc id="diagram-desc">{escape(d["caption"])}。README 简版；完整分支和边界保留在对应 notes 文档。</desc>',
        '<style>text{font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",Arial,sans-serif}path{stroke-linejoin:round}</style>',
        '<defs><marker id="arrow" viewBox="0 0 10 8" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L10 4L0 8Z" fill="#3b82f6"/></marker></defs>',
        f'<rect data-graph-role="background" width="{w}" height="{h}" fill="white"/>'])
    p.append('<g id="heading" data-graph-role="reserved" data-graph-bounds="60 24 1340 123">')
    p.extend([text(60,64,d['title'],34,600,anchor='start'),text(60,108,d['caption'],20,color='#6b7280',anchor='start'),'</g>'])
    assert length(d['caption'],20)<1280,(d['id'],'caption too long')
    # 所有卡片只放标题与最多一行提示，不将长文藏进缩小字号里。
    for n in d['nodes']:
        x,y,nw,nh=n['x'],n['y'],n['width'],n['height']
        size=26
        while size>22 and length(n['title'],size)>nw-36:size-=1
        assert length(n['title'],size)<=nw-36,(d['id'],n['title'])
        assert length(n['sub'],19)<=nw-36,(d['id'],n['sub'])
        stroke='#9ca3af' if n['kind']=='diamond' else '#d1d5db'
        fill='white' if n['kind']=='diamond' or n['optional'] else '#f9fafb'
        dash=' stroke-dasharray="6 5"' if n['optional'] else ''
        p.append(f'<g id="{n["id"]}" data-node-id="{n["id"]}" data-graph-role="node" data-graph-bounds="{x} {y} {x+nw} {y+nh}">')
        # 问号卡片表示判定节点；保持 Notion 的矩形卡片与统一字级。
        p.extend([f'<rect x="{x}" y="{y}" width="{nw}" height="{nh}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>',
            text(x+nw/2,y+41,n['title'],size,600),text(x+nw/2,y+74,n['sub'],19,color='#6b7280'),'</g>'])
    for i,e in enumerate(d['edges']):
        key=f'edge-{i}'
        points=e['points'];route='M '+' L '.join(f'{x} {y}' for x,y in points)
        p.append(f'<path id="{key}" data-graph-role="edge" data-edge-id="{key}" data-source="{e["source"]}" data-target="{e["target"]}" d="{route}" fill="none" stroke="#3b82f6" stroke-width="1.9" marker-end="url(#arrow)"/>')
        if e['label']:
            x,y=e['label_at'];tw=length(e['label'],18)+4
            p.append(f'<g id="{key}-label" data-graph-role="label" data-owner="{key}" data-graph-bounds="{x-tw/2} {y-21} {x+tw/2} {y+5}">')
            p.extend([text(x,y,e['label'],18,color='#374151'),'</g>'])
    p.append('</svg>')
    svg='\n'.join(p)
    path=ROOT/'svg'/f'{d["id"]}.svg';path.write_text(svg,encoding='utf-8')
    report={}
    for check in ['xml','markers','collisions','geometry','composition']:
        ok,details=run_check(path,check);report[check]={'ok':ok,'details':details}
    # Mermaid 与矢量图使用相同简版节点、连接和说明，避免改图不改源码。
    m=['flowchart LR','    %% README 简版；完整分支见 notes 文档。']
    for n in d['nodes']:
        title=n['title'].replace('"','&quot;');sub=n['sub'].replace('"','&quot;')
        m.append(f'    {n["id"]}["{title}<br/>{sub}"]')
    for e in d['edges']:
        label=('|"'+e['label'].replace('"','&quot;')+'"|') if e['label'] else ''
        m.append(f'    {e["source"]} -->{label} {e["target"]}')
    m += ['    classDef default fill:#f9fafb,stroke:#d1d5db,color:#111827;','    classDef optional fill:#ffffff,stroke:#d1d5db,stroke-dasharray:6 5,color:#111827;','    linkStyle default stroke:#3b82f6;']
    optional=[n['id'] for n in d['nodes'] if n['optional']]
    if optional:m.append('    class '+','.join(optional)+' optional;')
    (ROOT/'mermaid'/f'{d["id"]}.mmd').write_text('\n'.join(m)+'\n',encoding='utf-8')
    return report


def notes_and_readme(manifest):
    # 默认显示简版图；原图完整保留并折叠，细节资料不丢失。
    for note in sorted({d['note'] for d in manifest['diagrams']}):
        path=ROOT/note;original=path.read_text(encoding='utf-8')
        if '<!-- readme-diagram:' in original:continue
        diagrams=[d for d in manifest['diagrams'] if d['note']==note]
        blocks=list(re.finditer(r'```mermaid[^\n]*\n.*?```',original,re.S))
        assert len(blocks)==len(diagrams),(note,len(blocks),len(diagrams))
        count=iter(diagrams)
        def replace(match):
            d=next(count)
            return f'<!-- readme-diagram:{d["id"]} -->\n![{d["title"]}](../{d["png"]})\n\n<details>\n<summary>展开原始完整流程</summary>\n\n'+match.group(0)+'\n\n</details>'
        path.write_text(re.sub(r'```mermaid[^\n]*\n.*?```',replace,original,flags=re.S),encoding='utf-8')
    out=['# AI-Robot 架构与流程图','', '9 个主题、27 张 README 简版图，统一采用 Notion 极简风。每张只展示主链与关键分支；详细条件、异常、阈值和源码位置见对应说明。','',
         '直接打开 [图册](index.html) 浏览，或按下方主题阅读。PNG 可直接嵌入 Markdown；SVG 可无损放大，Mermaid 可编辑。','']
    for topic in manifest['topics']:
        ds=[d for d in manifest['diagrams'] if d['topicIndex']==topic['index']]
        first=ds[0]
        out += ['## '+topic['title'],'',f'![{first["title"]}]({first["png"]})','',f'[SVG]({first["svg"]}) · [Mermaid]({first["source"]}) · [完整说明]({first["note"]})','']
        if len(ds)>1:
            out += ['<details>','<summary>查看该主题的其他流程</summary>','']
            for d in ds[1:]:out += ['### '+d['title'],'',f'![{d["title"]}]({d["png"]})','',f'[SVG]({d["svg"]}) · [Mermaid]({d["source"]})','']
            out += ['</details>','']
    out += ['## 编辑与重新生成','',
        '- `readme_specs.py`：27 张简版图的节点、连接和布局。','- `notes/`：原始完整说明；默认展示新图，原 Mermaid 流程折叠保留。',
        '- `render.cjs`：本地批量生成 SVG、PNG、缩略图和图册。','- `svg-validation.json`、`render-report.json`：构图与导出检查结果。','',
        '使用 Node.js 运行 `render.cjs`。可通过 `DIAGRAM_PYTHON`、`DIAGRAM_RUNTIME_MODULES`、`DIAGRAM_FONT`、`FIREWORKS_SKILL_ROOT` 指定本机依赖。','',
        '本目录是技术文档图示，不代表当前运行环境已启用可选功能，也不将历史评测结果视为当前版本认证。','']
    (ROOT/'README.md').write_text('\n'.join(out),encoding='utf-8')


def index(manifest):
    groups=[]
    for topic in manifest['topics']:
        cards=[]
        for d in manifest['diagrams']:
            if d['topicIndex']!=topic['index']:continue
            cards.append(f'<article><a class="image" href="{d["svg"]}" target="_blank"><img src="previews/{d["id"]}.png" alt="{escape(d["title"])}" loading="lazy"></a><h3>{escape(d["title"])}</h3><p>{escape(d["caption"])}</p><footer><a href="{d["png"]}">PNG</a><a href="{d["svg"]}">SVG</a><a href="{d["source"]}">Mermaid</a><a href="{d["note"]}">说明</a></footer></article>')
        groups.append(f'<section id="topic-{topic["index"]}" data-topic="{topic["index"]}"><h2>{escape(topic["title"])}</h2><div class="grid">'+''.join(cards)+'</div></section>')
    buttons='<button class="active" data-filter="all">全部</button>'+''.join(f'<button data-filter="{t["index"]}">{escape(t["title"])}</button>' for t in manifest['topics'])
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI-Robot · README 流程图</title><style>*{box-sizing:border-box}body{margin:0;background:white;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}header,main{max-width:1500px;margin:auto;padding:32px}header{padding-bottom:20px}h1{font-size:30px;margin:0 0 10px}header p{color:#6b7280;font-size:15px}nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:24px}button{padding:9px 13px;border:1px solid #e5e7eb;border-radius:4px;background:white;color:#374151;cursor:pointer}button.active,button:hover{background:#f9fafb;border-color:#9ca3af}main{padding-top:0}section{margin:25px 0 42px}h2{font-size:23px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{border:1px solid #e5e7eb;border-radius:4px;padding:18px}.image{display:flex;align-items:center;justify-content:center;height:290px;background:white}img{display:block;max-width:100%;max-height:100%;object-fit:contain}h3{font-size:18px;margin:18px 0 9px}article p{font-size:13px;color:#6b7280;line-height:1.7;min-height:44px}footer{display:flex;gap:20px;margin-top:14px}a{color:#374151;text-decoration:none}a:hover{text-decoration:underline}[hidden]{display:none!important}@media(max-width:760px){header,main{padding:20px}.grid{grid-template-columns:1fr}.image{height:auto;min-height:180px}h1{font-size:24px}}</style><header><h1>AI-Robot · 架构与流程</h1><p>9 个主题 · 27 张简版图 · Notion 极简风　　点击图片可打开矢量原图</p><nav>'''+buttons+'''</nav></header><main>'''+''.join(groups)+'''</main><script>document.querySelectorAll('button[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('button[data-filter]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('section[data-topic]').forEach(s=>s.hidden=b.dataset.filter!=='all'&&b.dataset.filter!==s.dataset.topic);});</script></html>'''
    (ROOT/'index.html').write_text(page,encoding='utf-8')


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    for sub in ['svg','png','mermaid','previews']:(ROOT/sub).mkdir(exist_ok=True)
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    old={d['id']:d for d in manifest['diagrams']}
    assert set(old)=={d['id'] for d in DIAGRAMS}
    reports=[]
    for d in DIAGRAMS:
        result=render(d)
        reports.append({'id':d['id'],'checks':result})
        old[d['id']].update(title=d['title'],caption=d['caption'],width=d['width'],height=d['height'],style=4,nodeCount=len(d['nodes']),edgeCount=len(d['edges']))
    manifest.update(source='README 简版；节点、连接及各输出均来自 readme_specs.py，完整原始流程折叠保存在 notes',style='4 / Notion Clean',presentation='readme-simple')
    (ROOT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'diagram-specs.json').write_text(json.dumps(DIAGRAMS,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'svg-validation.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    notes_and_readme(manifest);index(manifest)
    failed=[r for r in reports if not all(c['ok'] for c in r['checks'].values())]
    print(json.dumps({'diagrams':len(reports),'nodes':sum(len(d['nodes']) for d in DIAGRAMS),'failed':failed},ensure_ascii=False))
    if failed:raise SystemExit(1)

if __name__=='__main__':main()
