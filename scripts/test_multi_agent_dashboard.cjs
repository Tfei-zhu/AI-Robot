// S6 actual Chromium checks. Mocked responses and unmodified backend traffic
// are recorded separately. No live model requests are ever made by this script.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const evidence = path.resolve(process.env.S6_EVIDENCE_DIR || path.join(root, 'docs/evidence/s6-20261017'));
const out = process.env.S6_RUN_DIR ? path.join(evidence,process.env.S6_RUN_DIR) : evidence;
const fixtures = JSON.parse(fs.readFileSync(process.env.S6_FIXTURES || path.join(evidence, 'ui-fixtures.json'), 'utf8'));
const html = fs.readFileSync(path.join(root, 'app/static/dashboard.html'), 'utf8');
const frame = value => `data: ${JSON.stringify(value)}\n\n`;
const copy = value => JSON.parse(JSON.stringify(value));
const result = name => copy(fixtures.cases[name].at(-1).result);
const checks = [];
const backendResults = [];
const record = (name, source) => { checks.push({ name, source, status: 'passed' }); console.log('PASS', source, name); };
const state = page => page.locator('#goStatus').getAttribute('data-state');
const waitState = (page, value) => page.waitForFunction(s => document.querySelector('#goStatus').dataset.state === s, value);
const token = 's6-local-test-token';

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    page.on('pageerror', e => errors.push(e.message));
    let mode = 'passed', queried = null;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.host !== 'airobot.test') return route.abort();
      if (url.pathname === '/dashboard') return route.fulfill({ contentType: 'text/html', body: html });
      if (url.pathname.endsWith('/go/tasks/stream')) {
        let messages = copy(fixtures.cases[mode === 'drop' || mode === 'wrong-run' || mode === 'unknown' ? 'passed' : mode] || fixtures.cases.passed);
        if (mode === 'drop') messages = messages.filter(e => e.type !== 'go_done');
        if (mode === 'wrong-run') {
          const current = messages[0].run_id;
          const foreign = { type: 'go_done', run_id: 'f'.repeat(32), result: { ...result('passed'), run_id: 'f'.repeat(32), final_summary: 'FOREIGN-PASSED' } };
          messages = [messages[0], foreign, ...copy(fixtures.cases.failed).slice(1).map(e => ({ ...e, run_id: current,
            ...(e.result ? { result: { ...e.result, run_id: current } } : {}) }))];
        }
        if (mode === 'unknown') messages.at(-1).result.status = 'future-status';
        if (mode === 'suggestion') messages.at(-1).result.reviews[0].issues=[{issue_id:'s-1',severity:'suggestion',file:'solution.go',line:3,evidence:'命名可更清晰',repair_instruction:'可选：调整命名'}];
        if (mode === 'nonterminal-done') messages.at(-1).result.status = 'running';
        if (mode === 'missing-id') messages=messages.map((e,i)=>{if(i){delete e.run_id;if(e.result)delete e.result.run_id;}return e;});
        if (mode === 'bad-json') return route.fulfill({contentType:'text/event-stream',body:frame(messages[0])+'data: {not-json}\n\n'});
        if(mode==='legacy-stream')messages=[{type:'go_start',run_id:fixtures.legacy.run_id,workflow_version:'single-v1'},
          {type:'go_stage',stage:'generate',message:'正在生成代码'},...fixtures.legacy.attempts.map(attempt=>({type:'go_attempt',attempt})),
          {type:'go_done',result:fixtures.legacy}];
        return route.fulfill({ contentType: 'text/event-stream', body: messages.map(frame).join('').replaceAll('\n', '\r\n') });
      }
      if (url.pathname.startsWith('/api/v1/go/tasks/')) return route.fulfill({ json: queried || fixtures.legacy });
      if (url.pathname.endsWith('/traces')) return route.fulfill({ json: { entries: [], summary: { total: 0, cache_hit_rate: 0, p95_ms: 0 } } });
      return route.fulfill({ json: { llm_model: 'UI response fixture', embedding_model: 'not called', total_chunks: 0 } });
    });
    await page.goto('http://airobot.test/dashboard');
    await page.locator('#adminToken').fill(token);
    for (const [name, expected] of [['passed', 'passed'], ['repair', 'passed'], ['failed', 'failed'], ['timeout', 'timeout'], ['unavailable', 'unavailable'], ['unknown', 'unknown'], ['drop', 'disconnected'], ['wrong-run', 'failed'], ['nonterminal-done','unknown'], ['missing-id','unknown'], ['bad-json','unknown'], ['suggestion','passed'], ['legacy-stream','passed']]) {
      mode = name;
      await page.locator('#goStart').click();
      await waitState(page, expected);
      await page.waitForFunction(() => !document.querySelector('#goStart').disabled);
      assert.equal(await page.locator('#goCancel').isDisabled(), true);
      if (name === 'repair') {
        assert.equal(await page.locator('[data-section=artifact]').count(), 2);
        assert.equal(await page.locator('[data-section=review]').count(), 2);
        assert.match(await page.locator('#goTimeline').textContent(), /委派.*生成/s);
        assert.match(await page.locator('#goTimeline').textContent(), /审查/);
        assert.match(await page.locator('#goTimeline').textContent(), /修复/);
        assert.match(await page.locator('#goTimeline').textContent(), /修复 · 第 1 轮/);
        assert.match(await page.locator('[data-diff=true] pre').textContent(), /- .*return nil/);
        assert.match(await page.locator('.go-blocking').first().textContent(), /i-1/);
        assert.match(await page.locator('[data-section=budget]').textContent(), /共享异常重试：0 \/ 1/);
        await page.locator('[data-diff=true] summary').click();
        assert.equal(await page.locator('[data-diff=true] pre').isVisible(),true);
      }
      if (name === 'wrong-run') assert.doesNotMatch(await page.locator('#goReport').textContent(), /FOREIGN-PASSED/);
      if(name==='suggestion'){
        assert.equal(await page.locator('[data-section=artifact]').count(),1);
        assert.match(await page.locator('.go-suggestion').textContent(),/s-1/);
        assert.doesNotMatch(await page.locator('.go-blocking').textContent(),/s-1/);
      }
      if(name==='legacy-stream'){
        assert.match(await page.locator('#goTimeline').textContent(),/单流程模型/);
        assert.doesNotMatch(await page.locator('#goTimeline').textContent(),/主 Agent 委派|主 Agent · 审查/);
      }
      await page.locator('#goValidation').screenshot({ path: path.join(out, `mock-${name}.png`) });
      record(name, 'browser response replacement; captured service shapes, model + validator substitutes');
    }
    // A slow reader/transport may still deliver an older request after abort.
    // Deliberately ignore AbortSignal in this replacement so isolation cannot
    // pass merely because fetch happened to cancel quickly.
    await page.evaluate(async data => {
      window.originalGoFetch = window.fetch;
      window.streams = [];
      window.fetch = async (url, options) => {
        if (!String(url).endsWith('/go/tasks/stream')) return window.originalGoFetch(url, options);
        const id = (window.streams.length ? 'b' : 'a').repeat(32);
        return new Response(new ReadableStream({ start(c) { window.streams.push(c); c.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type:'go_start', run_id:id })}\n\n`)); } }), { headers:{'Content-Type':'text/event-stream'} });
      };
      window.oldTask = startGoTask();
    }, null);
    await page.waitForFunction(() => document.querySelector('#goRunId').value === 'a'.repeat(32));
    await page.evaluate(() => { cancelGoTask(); window.newTask = startGoTask(); });
    await page.waitForFunction(() => document.querySelector('#goRunId').value === 'b'.repeat(32));
    await page.evaluate(async passed => {
      const push = (i, event) => window.streams[i].enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      push(1, {type:'go_progress', run_id:'b'.repeat(32), result:{...passed,run_id:'b'.repeat(32)}});
      push(1, {type:'go_stage', run_id:'b'.repeat(32), stage:'finish', status:'passed', message:'intermediate-passed'});
      push(0, {type:'go_done', run_id:'a'.repeat(32), result:{...passed,run_id:'a'.repeat(32)}});
      window.streams[0].close(); await window.oldTask;
    }, result('passed'));
    assert.equal(await state(page), 'running');
    assert.equal(await page.locator('#goStart').isDisabled(), true);
    assert.equal(await page.locator('#goRunId').inputValue(), 'b'.repeat(32));
    await page.evaluate(async failed => {
      window.streams[1].enqueue(new TextEncoder().encode(`data: ${JSON.stringify({type:'go_done',run_id:'b'.repeat(32),result:{...failed,run_id:'b'.repeat(32)}})}\n\n`));
      window.streams[1].close();await window.newTask;window.fetch=window.originalGoFetch;
    }, result('failed'));
    assert.equal(await state(page), 'failed');
    record('intermediate passed never green; old stream/finally cannot overwrite new task or unlock its controls', 'browser fetch/ReadableStream replacement');
    await page.evaluate(id => {
      window.originalGoFetch = window.fetch;
      window.fetch = async (url,options) => String(url).endsWith(id) ? await new Promise(resolve => window.resolveOldReport=resolve) : window.originalGoFetch(url,options);
      document.querySelector('#goRunId').value=id;window.oldQuery=loadGoTask();
    }, 'c'.repeat(32));
    await page.waitForFunction(() => typeof window.resolveOldReport === 'function');
    mode = 'passed';await page.locator('#goStart').click();await waitState(page, 'passed');
    const newest = await page.locator('#goRunId').inputValue();
    await page.evaluate(async old => {
      window.resolveOldReport(new Response(JSON.stringify({...old,run_id:'c'.repeat(32),final_summary:'OLD-QUERY'}), {headers:{'Content-Type':'application/json'}}));
      await window.oldQuery;window.fetch=window.originalGoFetch;
    }, result('failed'));
    assert.equal(await state(page), 'passed');assert.equal(await page.locator('#goRunId').inputValue(), newest);
    assert.doesNotMatch(await page.locator('#goReport').textContent(), /OLD-QUERY/);
    record('late historical query cannot overwrite newer run', 'browser fetch replacement');

    queried = copy(fixtures.legacy);
    await page.locator('#goRunId').fill(queried.run_id);await page.locator('#goLoad').click();await waitState(page, 'passed');
    assert.match(await page.locator('#goReport').textContent(), /旧版单流程报告/);
    assert.equal(await page.locator('#goReport > details').count(), queried.attempts.length);
    record('actual historical report shape remains readable', 'browser GET response replacement; historical Docker report file');

    queried = result('failed');
    const attack = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>';
    queried.task_spec.original_requirement = attack;
    queried.artifacts[0].files[0].content += '\n// ' + attack;
    queried.artifacts[0].change_summary = attack;
    queried.attempts[0].validation.stages[0].output = attack;
    queried.reviews[0].summary = attack;
    queried.reviews[0].issues = [ {issue_id:'xss',severity:'blocking',file:'solution.go',line:1,evidence:attack,repair_instruction:attack} ];
    queried.agent_calls[0].model=attack;queried.final_summary=attack;queried.token_usage=null;
    queried.context_stats={usage_complete:false,unknown_usage_calls:3,known_token_usage:{input_tokens:12},cost_estimate:null};
    await page.locator('#goRunId').fill(queried.run_id);await page.locator('#goLoad').click();await waitState(page, 'failed');
    assert.equal(await page.locator('#goReport img, #goReport script, #goReport iframe').count(), 0);
    assert.equal(await page.evaluate(() => Boolean(window.injected)), false);
    assert.match(await page.locator('#goReport').textContent(), /<img/);
    assert.match(await page.locator('[data-section=budget]').textContent(), /Token 用量：未知/);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => { const el=document.querySelector('#goValidation');return el.scrollWidth<=el.clientWidth; }), true);
    await page.locator('#goValidation').screenshot({path:path.join(out,'mock-text-safety-mobile.png')});
    await page.screenshot({path:path.join(out,'mock-mobile-viewport.png')});
    record('code/log/model/issue text renders inert; unknown usage; mobile no horizontal overflow', 'intentionally tampered browser response; not a valid server artifact');
    queried={...result('passed'),run_id:'e'.repeat(32)};
    await page.locator('#goRunId').fill('d'.repeat(32));await page.locator('#goLoad').click();await waitState(page,'unknown');
    assert.match(await page.locator('#goStatus').textContent(),/run_id 不匹配/);
    record('queried report run_id mismatch rejected', 'browser GET response replacement');

    const backend=process.env.S6_BACKEND_URL;
    if(backend){
      const real=await browser.newPage({viewport:{width:1280,height:950}});real.on('pageerror',e=>errors.push(e.message));
      const origin=new URL(backend).origin;
      let ready=false;
      for(let i=0;i<100;i++){
        try{const r=await real.request.get(backend+'/health',{timeout:500});if(r.ok()){ready=true;break;}}catch{}
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      assert.equal(ready,true,'local test backend must start');
      // Continue same-origin requests unchanged; do not fulfill any API response.
      await real.route('**/*', route => new URL(route.request().url()).origin===origin?route.continue():route.abort());
      await real.goto(backend+'/dashboard');await real.locator('#adminToken').fill(token);
      for(const [name,expected] of [['passed','passed'],['repair','passed'],['failed','failed']]){
        await real.locator('#goRequirement').fill(`[${name}] 等待 context 取消并返回 ctx.Err()，取消前不得提前返回`);
        await real.locator('#goStart').click();await waitState(real,expected);
        await real.waitForFunction(()=>!document.querySelector('#goStart').disabled);
        const id=await real.locator('#goRunId').inputValue();
        const response=await real.request.get(backend+'/api/v1/go/tasks/'+id,{headers:{Authorization:'Bearer '+token}});
        assert.equal(response.status(),200);const data=await response.json();
        assert.equal(data.status,expected);assert.equal(data.model_source,'fixture');
        assert.equal(data.attempts.every(a=>a.validation.container_removed),true);
        if(name==='repair')assert.equal(data.attempts.length,2);
        if(name==='passed')assert.equal(data.artifacts[0].artifact_hash,data.reviews[0].artifact_hash);
        backendResults.push({case:name,provenance:'real HTTP/FastAPI/LangGraph/SQLite; fixed role models; '+(process.env.S6_REAL_DOCKER==='1'?'real Docker':'validator substitute'),result:data});
        if(name==='repair'){
          await real.locator('[data-diff=true] summary').click();
          assert.equal(await real.locator('[data-diff=true] pre').isVisible(),true);
          await real.locator('#goValidation').screenshot({path:path.join(out,'backend-repair-live.png')});
        }
        await real.locator('#goLoad').click();await waitState(real,expected);
        await real.locator('#goValidation').screenshot({path:path.join(out,`backend-${name}.png`)});
        record(name,'real backend; fixed models; '+(process.env.S6_REAL_DOCKER==='1'?'real Docker':'validator substitute'));
      }
      await real.locator('#goRequirement').fill('[cancel] 等待取消的固定模型请求');await real.locator('#goStart').click();
      await real.waitForFunction(()=>document.querySelector('#goTimeline').textContent.includes('委派'));
      const cancelledId=await real.locator('#goRunId').inputValue();await real.locator('#goCancel').click();
      await waitState(real,'cancel_requested');await real.waitForFunction(()=>!document.querySelector('#goLoad').disabled);
      let cancelled;
      for(let i=0;i<40;i++){
        const response=await real.request.get(backend+'/api/v1/go/tasks/'+cancelledId,{headers:{Authorization:'Bearer '+token}});
        cancelled=await response.json();if(cancelled.status==='cancelled')break;
        await new Promise(resolve=>setTimeout(resolve,50));
      }
      assert.equal(cancelled.status,'cancelled');
      await real.locator('#goLoad').click();await waitState(real,'cancelled');
      backendResults.push({case:'cancelled',provenance:'real browser disconnect and backend persistence; blocking model substitute; no Docker launched',result:cancelled});
      record('cancel request distinct from server-confirmed cancelled','real browser abort + real backend GET');
      await real.locator('#goRunId').fill(fixtures.legacy.run_id);await real.locator('#goLoad').click();await waitState(real,'passed');
      assert.match(await real.locator('#goReport').textContent(),/旧版单流程报告/);
      await real.locator('#goValidation').screenshot({path:path.join(out,'backend-legacy.png')});
      record('legacy stored JSON through actual GET and browser','real backend; historical sample, no new validation');
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({browser:await browser.version(),checks,page_errors:errors,paid_models:'not_run'},null,2)+'\n');
    fs.writeFileSync(path.join(out,'backend-results.json'),JSON.stringify(backendResults,null,2)+'\n');
    console.log('S6 browser checks passed:',checks.length);
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
