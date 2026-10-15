// Render mockup screens with Playwright (Chromium) at 2x.
// node render_mockups.mjs <out-dir> <design> <scheme|all> <screen|all> [scale]
// Optional: MOCKUP_QUERY adds query parameters to every page, for example MOCKUP_QUERY="panel=plaque".
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
// Playwright and Chromium: PLAYWRIGHT_MODULE and CHROMIUM_PATH override where they are found.
const PW_DEFAULT = '/opt/node-tools/node_modules/playwright/index.mjs';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || (fs.existsSync(PW_DEFAULT) ? PW_DEFAULT : 'playwright'));
const CHROME = process.env.CHROMIUM_PATH || ['/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].find(p => fs.existsSync(p));
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const [outDir, design, schemeArg, screenArg, scaleArg] = process.argv.slice(2);
const SCHEMES = JSON.parse(fs.readFileSync(path.join(ROOT, 'system/schemes.json'), 'utf8'));
const SCREENS = ['atlas', 'peel', 'lesson', 'lessons', 'models', 'viewer', 'radiology', 'practice', 'histology', 'histology-library', 'settings'];
const schemes = schemeArg === 'all' ? Object.keys(SCHEMES[design].schemes) : schemeArg.split(',');
const screens = screenArg === 'all' ? SCREENS : screenArg.split(',');
const scale = parseFloat(scaleArg || '2');
const extra = (process.env.MOCKUP_QUERY || '').replace(/^[?&]+/, '');
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: scale });
page.on('pageerror', e => console.error('PAGEERROR', e.message));
page.on('console', m => { if (m.type() === 'error') console.error('CONSOLE', m.text()); });
for (const scheme of schemes) {
  for (const screen of screens) {
    const url = 'file://' + path.join(ROOT, 'app', design, 'index.html') + `?scheme=${scheme}&screen=${screen}` + (extra ? '&' + extra : '');
    await page.goto(url);
    await page.waitForFunction(() => document.documentElement.dataset.ready === '1', null, { timeout: 30000 });
    await page.waitForTimeout(150);
    const file = path.join(outDir, `${design}_${scheme}_${screen}.png`);
    await page.screenshot({ path: file, clip: { x: 0, y: 0, width: 1920, height: 1080 } });
    console.log(file);
  }
}
await browser.close();
