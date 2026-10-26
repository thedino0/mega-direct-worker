import { build } from 'esbuild';

await build({
  entryPoints: ['src/main.js'],
  bundle: true,
  format: 'esm',
  platform: 'neutral',
  target: 'es2022',
  outfile: 'mega-direct-worker.js',
  legalComments: 'none',
  charset: 'utf8',
  minifyWhitespace: true,
  logLevel: 'info',
});
