// 同一规格生成 SVG / Mermaid，再本地导出 PNG 与缩略图。
const fs=require('fs');
const path=require('path');
const os=require('os');
const {spawnSync}=require('child_process');
const bundled=path.join(os.homedir(),'.cache','codex-runtimes','codex-primary-runtime','dependencies');
const runtime=process.env.DIAGRAM_RUNTIME_MODULES||path.join(bundled,'node','node_modules');
const sharp=require(path.join(runtime,'sharp'));
const root=process.env.DIAGRAM_OUTPUT_ROOT||__dirname;

(async()=>{
  const python=process.env.DIAGRAM_PYTHON||path.join(bundled,'python',process.platform==='win32'?'python.exe':'bin/python3');
  const build=spawnSync(python,[path.join(__dirname,'generate_readme_diagrams.py')],{env:{...process.env,PYTHONIOENCODING:'utf-8'},encoding:'utf8'});
  if(build.status!==0)throw new Error(build.stdout+'\n'+build.stderr);
  process.stdout.write(build.stdout);
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
  const output=[];
  for(const d of manifest.diagrams){
    const svg=fs.readFileSync(path.join(root,d.svg));
    const png=path.join(root,d.png);
    await sharp(svg).png().toFile(png);
    const m=await sharp(png).metadata();
    if(m.width!==d.width||m.height!==d.height)throw new Error('图片尺寸不匹配：'+d.id);
    await sharp(png).resize({width:1000}).png().toFile(path.join(root,'previews',d.id+'.png'));
    output.push({id:d.id,width:m.width,height:m.height,bytes:fs.statSync(png).size});
  }
  // 刷新原图册已有的概览及详情预览名称，避免页面仍显示旧图。
  for(let start=0;start<27;start+=9){
    const tiles=[];
    for(let i=0;i<9;i++){
      const d=manifest.diagrams[start+i];
      const buffer=await sharp(path.join(root,d.png)).resize({width:460,height:285,fit:'contain',background:'white'}).png().toBuffer();
      tiles.push({input:buffer,left:i%3*470+5,top:Math.floor(i/3)*295+5});
    }
    await sharp({create:{width:1410,height:885,channels:4,background:'white'}}).composite(tiles).png().toFile(path.join(root,'previews','overview-'+(start/9+1)+'.png'));
  }
  for(const key of ['01-architecture-01','06-go-orchestration-02','08-context-management-02','09-verification-evaluation-02']){
    await sharp(path.join(root,'png',key+'.png')).resize({width:1000}).png().toFile(path.join(root,'previews','detail-'+key+'.png'));
  }
  // 仅供视觉检查：以 README 常用的 900px 阅读宽度生成九张审阅页。
  if(process.env.DIAGRAM_REVIEW_DIR){
    const target=process.env.DIAGRAM_REVIEW_DIR;fs.mkdirSync(target,{recursive:true});
    for(let start=0;start<27;start+=3){
      const input=[];let top=0;
      for(const d of manifest.diagrams.slice(start,start+3)){
        const height=Math.round(d.height*900/d.width);
        const buffer=await sharp(path.join(root,d.png)).resize({width:900}).png().toBuffer();
        input.push({input:buffer,left:0,top});top+=height+20;
      }
      await sharp({create:{width:900,height:top-20,channels:4,background:'white'}}).composite(input).png().toFile(path.join(target,'review-'+(start/3+1)+'.png'));
    }
  }
  fs.writeFileSync(path.join(root,'render-report.json'),JSON.stringify({style:'4 / Notion Clean',renderer:'sharp/librsvg',diagramCount:27,canonicalSource:'readme_specs.py',output},null,2));
  console.log(JSON.stringify({png:output.length,minWidth:Math.min(...output.map(x=>x.width)),maxHeight:Math.max(...output.map(x=>x.height))}));
})();
