// Website captures for the gallery: first viewport on desktop (2x) and phone (2x), and the whole page with reduced
// motion (so the scroll-driven parts show their static layout) at desktop width, half scale.
// node shot_gallery.mjs <out-dir> <design> <scheme> [full]
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
// Playwright and Chromium: PLAYWRIGHT_MODULE and CHROMIUM_PATH override where they are found.
const PW_DEFAULT = '/opt/node-tools/node_modules/playwright/index.mjs';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || (fs.existsSync(PW_DEFAULT) ? PW_DEFAULT : 'playwright'));
const CHROME = process.env.CHROMIUM_PATH || ['/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].find(p => fs.existsSync(p));
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const [outDir, design, scheme, full] = process.argv.slice(2);
const url = 'file://' + path.join(ROOT, 'site', design, 'index.html') + `?scheme=${scheme}`;
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const errors = [];
async function shoot(viewport, scale, fullPage, reduce, out) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: scale, reducedMotion: reduce ? 'reduce' : 'no-preference' });
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await page.evaluate(async () => {           // load lazy images and settle reveal animations
    for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }
    window.scrollTo(0, 0); await new Promise(r => setTimeout(r, 500));
  });
  await page.screenshot({ path: out, fullPage });
  await page.close();
  console.log(out);
}
const base = path.join(outDir, `${design}_${scheme}`);
await shoot({ width: 1440, height: 900 }, 2, false, false, `${base}_desktop.png`);
if (full) {
  await shoot({ width: 390, height: 844 }, 2, false, false, `${base}_mobile.png`);
  await shoot({ width: 1440, height: 900 }, 1, true, true, `${base}_page.png`);
}
if (errors.length) console.log('PAGE ERRORS:\n' + [...new Set(errors)].join('\n'));
await browser.close();
