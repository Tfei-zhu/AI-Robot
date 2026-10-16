// 使用真实长对话报告检查指标展示与未知用量；浏览器接口固定替换，不请求模型。
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const report=JSON.parse(fs.readFileSync(path.join(root,'eval/reports/context/p5-D-fixed.json'),'utf8'));
const stats=report.results.at(-1).turns.at(-1).context_stats;
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||undefined});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('http://context.test/**',route=>route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'app/static/dashboard.html'),'utf8')}));
    await page.goto('http://context.test/dashboard');
    await page.evaluate(data=>renderContextStats(data),stats);
    const text=await page.locator('#contextStats').textContent();
    assert.match(text,/enforce/);assert.match(text,/摘要版本/);assert.match(text,/检索请求\/执行\/复用/);
    assert.match(text,new RegExp(String(stats.token_usage.total_tokens)));
    await page.evaluate(()=>renderContextStats({model_calls:1,token_usage:null,cost_estimate:null,context_mode:'<img src=x onerror=alert(1)>'}));
    assert.match(await page.locator('#contextStats').textContent(),/Token 未知 · 金额 未知/);
    assert.equal(await page.locator('#contextStats img').count(),0);
    assert.deepEqual(errors,[]);
    fs.mkdirSync(path.join(root,'eval/reports/context'),{recursive:true});
    await page.locator('#contextStats').screenshot({path:path.join(root,'eval/reports/context/dashboard.png')});
    console.log('上下文控制台通过：真实计量显示、未知用量不当零、纯文本隔离、无脚本异常');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
