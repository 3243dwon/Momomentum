// Copies the scanner's JSON output into the Vite static folder so the
// SvelteKit build serves them at /data/*.json. Runs before dev + build.
import { cp, mkdir, readdir, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..', '..');
const SRC = join(ROOT, 'data');
const DST = join(__dirname, '..', 'static', 'data');

if (!existsSync(SRC)) {
  console.warn(`[sync-data] source not found: ${SRC} — skipping`);
  process.exit(0);
}

await mkdir(DST, { recursive: true });

const files = (await readdir(SRC)).filter(
  (f) => f.endsWith('.json') && !f.startsWith('.')
);
for (const f of files) {
  const srcPath = join(SRC, f);
  const dstPath = join(DST, f);
  if ((await stat(srcPath)).isFile()) {
    await cp(srcPath, dstPath);
    console.log(`[sync-data] ${f}`);
  }
}
console.log(`[sync-data] copied ${files.length} JSON files into static/data/`);
