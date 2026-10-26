import { DEBUG } from './config.js';

export function log(stage, fields = {}) {
  if (DEBUG) console.log(JSON.stringify({ stage, ...fields }));
}

export function logError(stage, fields = {}) {
  console.error(JSON.stringify({ stage, ...fields }));
}
