// 真实验证报告驱动界面验收；接口响应在浏览器中替换，不使用模型密钥。
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'app/static/dashboard.html'), 'utf8');
const report = JSON.parse(fs.readFileSync(path.join(root, 'docs/go-validation-fixture-report.json'), 'utf8'));
const result = report.results.find(r => r.scenario === 'context_cancel' && r.attempts.length === 2);
const event = value => `data: ${JSON.stringify(value)}\n\n`;
(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    const errors = [];page.on('pageerror', error => errors.push(error.message));
    let mode = 'complete';
    await page.route('http://airobot.test/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/dashboard') return route.fulfill({ contentType: 'text/html', body: html });
      if (url.pathname.endsWith('/go/tasks/stream')) {
        let body = event({ type: 'go_start', run_id: result.run_id });
        if (mode === 'complete') {
          body += event({ type: 'go_stage', stage: 'repair', message: '收到真实测试错误，正在修复' });
          for (const attempt of result.attempts) body += event({ type: 'go_attempt', attempt });
          body += event({ type: 'go_done', result });
        }
        return route.fulfill({ contentType: 'text/event-stream', body });
      }
      if (url.pathname.startsWith('/api/v1/go/tasks/')) return route.fulfill({ json: result });
      if (url.pathname.endsWith('/traces')) return route.fulfill({ json: { entries: [], summary: { total: 0, cache_hit_rate: 0, p95_ms: 0 } } });
      return route.fulfill({ json: { llm_model: 'UI 测试固定响应', embedding_model: '未调用', total_chunks: 0 } });
    });
    await page.goto('http://airobot.test/dashboard');
    await page.locator('#adminToken').fill('dashboard-test-token');
    await page.locator('#goStart').click();
    await page.waitForFunction(() => document.querySelector('#goStatus').textContent.startsWith('验证通过'));
    assert.equal(await page.locator('#goReport > details').count(), 2);
    assert.match(await page.locator('#goReport').textContent(), /验证失败/);
    assert.match(await page.locator('#goReport').textContent(), /TestServer/);
    assert.match(await page.locator('#goReport').textContent(), /人工固定模型输出/);
    assert.equal(await page.locator('#goRunId').inputValue(), result.run_id);
    fs.mkdirSync(path.join(root, 'eval/reports/go'), { recursive: true });
    await page.locator('#goValidation').screenshot({ path: path.join(root, 'eval/reports/go/dashboard.png') });
    await page.locator('#goLoad').click();
    await page.waitForFunction(() => document.querySelector('#goReport > details') !== null);
    // 恶意代码、日志、修改说明只能成为文本，不能执行页面脚本。
    await page.evaluate(r => { r.attempts[0].change_summary = '<img src=x onerror="window.injected=true">';renderGoResult(r); }, result);
    assert.equal(await page.locator('#goReport img').count(), 0);
    assert.equal(await page.evaluate(() => !!window.injected), false);
    mode = 'incomplete';await page.locator('#goStart').click();
    await page.waitForFunction(() => document.querySelector('#goStatus').textContent.startsWith('任务失败：流提前结束'));
    assert.equal(await page.locator('#goStart').isEnabled(), true);
    assert.equal(await page.locator('#goCancel').isDisabled(), true);
    assert.deepEqual(errors, []);
    console.log('Dashboard 通过：失败/修复展示、真实日志、报告读取、文本隔离、提前断流处理，无页面脚本错误');
  } finally { await browser.close(); }
})().catch(error => { console.error(error);process.exitCode = 1; });
