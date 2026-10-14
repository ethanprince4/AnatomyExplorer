// Screenshot a site page for review: desktop first viewport, desktop full page (half scale), mobile first viewport,
// mobile full page. node shot_site.mjs <html file> <out prefix> [scheme]
import fs from 'fs';
import path from 'path';
// Playwright and Chromium: PLAYWRIGHT_MODULE and CHROMIUM_PATH override where they are found.
const PW_DEFAULT = '/opt/node-tools/node_modules/playwright/index.mjs';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || (fs.existsSync(PW_DEFAULT) ? PW_DEFAULT : 'playwright'));
const CHROME = process.env.CHROMIUM_PATH || ['/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].find(p => fs.existsSync(p));
const [file, prefix, scheme] = process.argv.slice(2);
const url = 'file://' + path.resolve(file) + (scheme ? `?scheme=${scheme}` : '');
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const errors = [];
async function shoot(viewport, scale, full, out) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: scale });
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await page.evaluate(async () => {           // load lazy images and settle reveal animations
    for (let y = 0; y < document.body.scrollHeight; y += 600) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 40)); }
    window.scrollTo(0, 0); await new Promise(r => setTimeout(r, 300));
  });
  await page.screenshot({ path: out, fullPage: full });
  await page.close();
  console.log(out);
}
await shoot({ width: 1440, height: 900 }, 1, false, `${prefix}_desktop.png`);
await shoot({ width: 1440, height: 900 }, 0.5, true, `${prefix}_desktop_full.png`);
await shoot({ width: 390, height: 844 }, 2, false, `${prefix}_mobile.png`);
await shoot({ width: 390, height: 844 }, 1, true, `${prefix}_mobile_full.png`);
if (errors.length) console.log('PAGE ERRORS:\n' + [...new Set(errors)].join('\n'));
await browser.close();
