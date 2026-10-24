/* QA-only generated docs review, using the prestarted browser server. */
const fs = require('node:fs');
const path = require('node:path');
const deps = process.env.QA_UX_NODE_MODULES || '/private/tmp/sentinel-qa-ux-20261002/node_modules';
const { chromium, firefox, webkit } = require(path.join(deps, 'playwright'));
const artifacts = path.join(__dirname, 'artifacts');
const origin = 'http://127.0.0.1:8767';
const report = { started_utc: new Date().toISOString(), browsers: [], externalRequestsBlocked: [] };

async function inspect(name, browserType) {
  let browser;
  const result = { name, errors: [], browserVersion: null };
  report.browsers.push(result);
  try {
    browser = await browserType.connect(process.env.PW_TEST_CONNECT_WS_ENDPOINT, { timeout: 15000 });
    result.browserVersion = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === origin) return route.continue();
      const asset = url.pathname.split('/').pop();
      if (['swagger-ui-bundle.js', 'swagger-ui.css'].includes(asset)) {
        return route.fulfill({ path: path.join(deps, 'swagger-ui-dist', asset), contentType: asset.endsWith('.js') ? 'application/javascript; charset=utf-8' : 'text/css; charset=utf-8' });
      }
      report.externalRequestsBlocked.push({ browser: name, host: url.host, pathname: url.pathname });
      return route.abort('blockedbyclient');
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on('pageerror', e => result.errors.push(e.message));
    const response = await page.goto(`${origin}/docs`);
    await page.getByRole('heading', { name: /Sentinel API/ }).waitFor();
    result.httpStatus = response.status();
    result.operationCount = await page.locator('.opblock').count();
    result.title = await page.title();
    result.headings = await page.locator('h1,h2,h3').allTextContents();
    result.landmarks = await page.locator('main,[role=main]').count();
    result.desktopOverflow = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }));
    result.navigationTiming = await page.evaluate(() => performance.getEntriesByType('navigation')[0].toJSON());
    await page.screenshot({ path: path.join(artifacts, `ux-${name}-desktop.png`), fullPage: true });
    if (name === 'chromium') {
      await page.addScriptTag({ path: path.join(deps, 'axe-core', 'axe.min.js') });
      result.axe = await page.evaluate(async () => {
        const r = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'] } });
        return { violations: r.violations, incomplete: r.incomplete.map(x => ({ id: x.id, nodes: x.nodes.length })), passes: r.passes.length };
      });
      result.keyboard = [];
      for (let i = 0; i < 8; i++) {
        await page.keyboard.press('Tab');
        result.keyboard.push(await page.evaluate(() => ({ tag: document.activeElement.tagName, text: document.activeElement.textContent.trim().slice(0, 100), expanded: document.activeElement.getAttribute('aria-expanded') })));
      }
      const operation = page.locator('#operations-approvals-create_v1_approvals_post');
      await operation.locator('.opblock-summary-control').focus();
      await page.keyboard.press('Enter');
      result.keyboardExpandsOperation = await operation.locator('.opblock-body').isVisible();
      result.expandedOperationSemantics = await operation.ariaSnapshot();
      result.focusOutline = await page.evaluate(() => ({ style: getComputedStyle(document.activeElement).outlineStyle, width: getComputedStyle(document.activeElement).outlineWidth }));
      await operation.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(artifacts, 'ux-chromium-approval-expanded.png') });
      await page.setViewportSize({ width: 375, height: 812 });
      result.mobileOverflow = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }));
      await page.screenshot({ path: path.join(artifacts, 'ux-chromium-mobile.png'), fullPage: true });
      await page.screenshot({ path: path.join(artifacts, 'ux-chromium-mobile-viewport.png') });

      const loadingPage = await context.newPage();
      let releaseSchema;
      let requestSeen;
      const schemaGate = new Promise(resolve => { releaseSchema = resolve; });
      const seenGate = new Promise(resolve => { requestSeen = resolve; });
      await loadingPage.route('**/openapi.json', async route => { requestSeen(); await schemaGate; await route.continue(); });
      await loadingPage.goto(`${origin}/docs`);
      await seenGate;
      result.loadingText = await loadingPage.locator('body').innerText();
      await loadingPage.screenshot({ path: path.join(artifacts, 'ux-chromium-loading.png') });
      releaseSchema();
      await loadingPage.getByRole('heading', { name: /Sentinel API/ }).waitFor();
      await loadingPage.close();

      const errorPage = await context.newPage();
      await errorPage.route('**/openapi.json', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Synthetic QA schema outage"}' }));
      await errorPage.goto(`${origin}/docs`);
      await errorPage.getByText('Failed to load API definition.').waitFor();
      result.errorText = await errorPage.locator('body').innerText();
      result.errorAlerts = await errorPage.getByRole('alert').count();
      await errorPage.screenshot({ path: path.join(artifacts, 'ux-chromium-schema-error.png') });
      await errorPage.close();

      const emptyPage = await context.newPage();
      await emptyPage.route('**/openapi.json', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ openapi: '3.1.0', info: { title: 'Sentinel API', version: 'QA empty state' }, paths: {} }) }));
      await emptyPage.goto(`${origin}/docs`);
      await emptyPage.getByText('No operations defined in spec!').waitFor();
      result.emptyText = await emptyPage.locator('body').innerText();
      await emptyPage.screenshot({ path: path.join(artifacts, 'ux-chromium-empty-schema.png') });
      await emptyPage.close();
    }
    await context.close();
  } catch (error) {
    result.blocker = error.message;
  } finally {
    if (browser) await browser.close();
  }
}

(async () => {
  for (const [name, type] of [['chromium', chromium], ['firefox', firefox], ['webkit', webkit]]) await inspect(name, type);
  report.ended_utc = new Date().toISOString();
  fs.writeFileSync(path.join(artifacts, 'ux-browser-report.json'), JSON.stringify(report, null, 2));
  const summary = report.browsers.map(({ name, browserVersion, title, httpStatus, operationCount, errors, blocker, axe, mobileOverflow, keyboardExpandsOperation, loadingText, errorText, emptyText }) => ({ name, browserVersion, title, httpStatus, operationCount, errors, blocker, axeViolations: axe?.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })), axeIncomplete: axe?.incomplete, mobileOverflow, keyboardExpandsOperation, loadingText, errorText, emptyText }));
  fs.writeFileSync(path.join(artifacts, 'ux-browser-summary.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
})();
