import { checkWorkerKey } from './auth.js';
import { jsonResponse, optionsResponse } from './http.js';
import { log, logError } from './log.js';
import { WorkerError } from './errors.js';
import { deriveFileKey, deriveFolderKey } from './crypto.js';
import {
  buildFileResult,
  buildFolderFileResult,
  buildFolderResult,
  fetchFolderNodes,
  fetchMegaFile,
  parseMegaLink,
  readInput,
} from './mega.js';
import { htmlResponse } from './ui.js';

async function resolveRequest(request) {
  const started = Date.now();
  try {
    const input = await readInput(request);
    const link = parseMegaLink(input.url, input.key);
    log('parse', {
      kind: link.kind,
      handle: link.handle,
      keySource: input.keySource,
      selection: link.selection ? link.selection.type : null,
    });
    let result;
    if (link.kind === 'file') {
      const key = deriveFileKey(link.key);
      log('key_decode', {
        kind: 'file',
        keyChars: link.key.length,
        aesKeyBytes: key.length,
      });
      const item = await fetchMegaFile(link.handle);
      result = buildFileResult(link, key, item);
    } else {
      const key = deriveFolderKey(link.key);
      log('key_decode', {
        kind: 'folder',
        keyChars: link.key.length,
        aesKeyBytes: key.length,
      });
      const nodes = await fetchFolderNodes(link.handle);
      if (link.selection && link.selection.type === 'file') {
        result = await buildFolderFileResult(link, key, nodes, link.selection.handle);
      } else {
        const startHandle =
          link.selection && link.selection.type === 'folder' ? link.selection.handle : null;
        result = await buildFolderResult(link, key, nodes, startHandle);
      }
    }
    log('done', { ms: Date.now() - started });
    return jsonResponse(result);
  } catch (error) {
    if (error instanceof WorkerError) {
      logError('error', {
        code: error.code,
        status: error.status,
        megaCode: error.megaCode,
        message: error.message,
        ms: Date.now() - started,
      });
      return jsonResponse(
        { error: { code: error.code, message: error.message } },
        error.status
      );
    }
    logError('error', {
      code: 'internal',
      message: error instanceof Error ? error.message : String(error),
      ms: Date.now() - started,
    });
    return jsonResponse(
      { error: { code: 'internal', message: 'Something broke on our side.' } },
      500
    );
  }
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return optionsResponse();
    }
    const requestUrl = new URL(request.url);
    if (request.method === 'GET' && requestUrl.pathname === '/favicon.ico') {
      return new Response(null, {
        status: 204,
        headers: { 'Cache-Control': 'public, max-age=86400' },
      });
    }
    if (requestUrl.pathname === '/bot/resolve') {
      if (request.method !== 'POST') {
        return jsonResponse(
          { error: { code: 'method_not_allowed', message: 'Use POST.' } },
          405
        );
      }
      const auth = checkWorkerKey(request, env);
      if (!auth.ok) {
        logError('bot_auth', { code: auth.code, status: auth.status });
        return jsonResponse(
          { error: { code: auth.code, message: auth.message } },
          auth.status
        );
      }
      log('bot_resolve', {});
      return resolveRequest(request);
    }
    if (
      request.method === 'GET' &&
      (requestUrl.pathname === '/ui' ||
        (requestUrl.pathname === '/' &&
          !requestUrl.searchParams.has('url') &&
          !requestUrl.searchParams.has('link') &&
          !requestUrl.searchParams.has('key') &&
          !requestUrl.searchParams.has('k') &&
          (request.headers.get('accept') || '').includes('text/html')))
    ) {
      log('ui', { path: requestUrl.pathname });
      return htmlResponse();
    }
    log('request', { method: request.method });
    return resolveRequest(request);
  },
};
