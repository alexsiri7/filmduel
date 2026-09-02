import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// process.cwd() in vitest resolves to the frontend root (where vite.config.js lives)
const FRONTEND_ROOT = process.cwd();

const CDN_PATTERNS = [
  'fonts.googleapis.com',
  'fonts.gstatic.com',
];

// Files in the frontend that previously referenced Google Fonts CDN
const FILES_TO_CHECK = [
  ['index.html', resolve(FRONTEND_ROOT, 'index.html')],
  ['src/index.css', resolve(FRONTEND_ROOT, 'src/index.css')],
  ['src/main.jsx', resolve(FRONTEND_ROOT, 'src/main.jsx')],
];

describe('Google Fonts CDN guard', () => {
  it.each(FILES_TO_CHECK)('%s contains no Google Fonts CDN references', (_name, filePath) => {
    const content = readFileSync(filePath, 'utf-8');
    for (const pattern of CDN_PATTERNS) {
      expect(
        content,
        `Found CDN reference "${pattern}" in ${_name} — use self-hosted @fontsource packages instead`
      ).not.toContain(pattern);
    }
  });
});
