// Rasterise SVG files to PNG with Chromium, keeping transparency.
//   node tools/raster_svg.mjs jobs.json
// jobs.json: [{ "svg": "path/to/file.svg", "out": "path/to/file.png", "size": 1024 }, ...]
// "size" is the output width and height in pixels; the SVG is drawn to fill it.
import fs from 'node:fs';
import path from 'node:path';

const PW_DEFAULT = '/opt/node-tools/node_modules/playwright/index.mjs';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || (fs.existsSync(PW_DEFAULT) ? PW_DEFAULT : 'playwright'));
const CHROME = process.env.CHROMIUM_PATH || ['/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].find(p => fs.existsSync(p));

const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const page = await browser.newPage({ deviceScaleFactor: 1 });
for (const job of jobs) {
  const size = job.size;
  // A data URL keeps the page free of file access; the SVGs are self-contained.
  const url = 'data:image/svg+xml;base64,' + fs.readFileSync(job.svg).toString('base64');
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<!doctype html><html><head><style>html,body{margin:0;background:transparent}
    img{display:block;width:${size}px;height:${size}px}</style></head><body><img src="${url}"></body></html>`);
  await page.waitForFunction(() => document.images[0].complete && document.images[0].naturalWidth > 0);
  fs.mkdirSync(path.dirname(job.out), { recursive: true });
  await page.screenshot({ path: job.out, omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}
await browser.close();
console.log(`rasterised ${jobs.length} files`);
