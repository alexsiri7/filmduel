import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

const CDN_PATTERNS = [
  'fonts.googleapis.com',
  'fonts.gstatic.com',
];

// Files in the frontend that previously referenced Google Fonts CDN
const FILES_TO_CHECK = [
  ['index.html', resolve('index.html')],
  ['src/index.css', resolve('src/index.css')],
  ['src/main.jsx', resolve('src/main.jsx')],
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
