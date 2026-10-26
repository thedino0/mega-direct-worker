import {
  ALLOWED_HOSTS,
  EXPIRES_IN,
  FILE_KEY_RE,
  FOLDER_KEY_RE,
  HANDLE_RE,
  MAX_API_BYTES,
  MAX_BATCH,
  MAX_FOLDER_FILES,
  MAX_FOLDER_NODES,
  MAX_INPUT,
  MEGA_API,
} from './config.js';
import { WorkerError } from './errors.js';
import { log, logError } from './log.js';
import { aes128EcbDecrypt } from './aes.js';
import { b64urlToBytes, decryptAttrs, extensionOf, nodeAttrKey } from './crypto.js';

function selectNodeKey(node, rootHandle) {
  if (typeof node.k !== 'string') {
    throw new WorkerError('decrypt_failed', 'MEGA sent a node without a key.', 502);
  }
  const alternatives = node.k.split('/');
  let selected = alternatives.find((alt) => alt.slice(0, 8) === rootHandle && alt[8] === ':');
  if (!selected) {
    selected = alternatives.find((alt) => alt.slice(0, 8) === node.h && alt[8] === ':');
  }
  if (!selected) {
    if (alternatives.length === 1) {
      selected = alternatives[0];
    } else {
      throw new WorkerError('decrypt_failed', 'MEGA sent an unexpected node key.', 502);
    }
  }
  const colon = selected.indexOf(':');
  if (colon <= 0 || colon === selected.length - 1) {
    throw new WorkerError('decrypt_failed', 'MEGA sent an unexpected node key.', 502);
  }
  return selected.slice(colon + 1);
}

function decryptNodeKey(node, linkKey, rootHandle) {
  const encoded = selectNodeKey(node, rootHandle);
  let ciphertext;
  try {
    ciphertext = b64urlToBytes(encoded);
  } catch {
    throw new WorkerError('decrypt_failed', 'MEGA sent metadata we could not decrypt.', 502);
  }
  const expected = node.t === 1 ? 16 : 32;
  if (ciphertext.length !== expected) {
    throw new WorkerError('decrypt_failed', 'MEGA sent metadata we could not decrypt.', 502);
  }
  return aes128EcbDecrypt(linkKey, ciphertext);
}

function findPublicRoot(nodes) {
  const handles = new Set(nodes.map((node) => node.h));
  const selfKeyed = nodes.find(
    (node) =>
      typeof node.k === 'string' &&
      node.k.split('/').some((alt) => alt.slice(0, 8) === node.h && alt[8] === ':')
  );
  if (selfKeyed) return selfKeyed;
  const orphan = nodes.find((node) => !handles.has(node.p));
  if (orphan) return orphan;
  throw new WorkerError('bad_response', 'MEGA did not return a folder root.', 502);
}

function findFolderRoot(nodes, startHandle) {
  if (!startHandle) return findPublicRoot(nodes);
  const selected = nodes.find((node) => node.h === startHandle && node.t === 1);
  if (!selected) {
    throw new WorkerError('not_found', 'That subfolder is not in this folder.', 404);
  }
  return selected;
}

function compareEntries(a, b) {
  if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
  const left = a.name.toLowerCase();
  const right = b.name.toLowerCase();
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function buildFolderIndex(nodes, linkKey, startHandle = null) {
  const publicRoot = findPublicRoot(nodes);
  const root = findFolderRoot(nodes, startHandle);
  const entries = new Map();
  for (const node of nodes) {
    if (node.t !== 0 && node.t !== 1) continue;
    if (typeof node.h !== 'string' || !HANDLE_RE.test(node.h)) continue;
    const nodeKey = decryptNodeKey(node, linkKey, publicRoot.h);
    let name = node.h;
    if (typeof node.a === 'string' && node.a.length > 0) {
      const attrs = decryptAttrs(node.a, nodeAttrKey(nodeKey, node.t));
      if (typeof attrs.n === 'string' && attrs.n.length > 0) name = attrs.n;
    }
    let size = 0;
    if (node.t === 0) {
      size = Number(node.s);
      if (!Number.isSafeInteger(size) || size < 0) {
        throw new WorkerError('bad_response', 'MEGA sent an invalid file size.', 502);
      }
    }
    entries.set(node.h, {
      handle: node.h,
      parent: node.p,
      name,
      isFolder: node.t === 1,
      size,
      children: [],
    });
  }
  const rootEntry = entries.get(root.h);
  if (!rootEntry) {
    throw new WorkerError('bad_response', 'MEGA did not return a folder root.', 502);
  }
  for (const entry of entries.values()) {
    if (entry.handle === root.h) continue;
    const parent = entries.get(entry.parent);
    if (parent && parent.isFolder) parent.children.push(entry);
    else if (root.handle === publicRoot.h) rootEntry.children.push(entry);
  }
  const files = [];
  const seen = new Set([root.h]);
  function walk(folder, path, depth) {
    if (depth > 64) {
      throw new WorkerError('folder_too_large', 'That folder is nested too deeply.', 413);
    }
    folder.children.sort(compareEntries);
    for (const child of folder.children) {
      if (seen.has(child.handle)) continue;
      seen.add(child.handle);
      const childPath = path ? `${path}/${child.name}` : child.name;
      if (child.isFolder) walk(child, childPath, depth + 1);
      else files.push({ node: child, path: childPath });
    }
  }
  walk(rootEntry, '', 0);
  files.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return { root: rootEntry, files };
}

function mapMegaError(code) {
  switch (code) {
    case -1:
      return ['mega_internal', 'MEGA had an internal error.', 502];
    case -2:
      return ['mega_rejected', 'MEGA rejected the request.', 502];
    case -3:
      return ['busy', 'MEGA is busy. Try again in a moment.', 503];
    case -4:
    case -6:
    case -19:
      return ['rate_limited', 'MEGA is rate-limiting requests. Try again shortly.', 429];
    case -5:
    case -25:
      return ['mega_failed', 'MEGA could not complete the request.', 502];
    case -7:
    case -10:
    case -12:
      return ['mega_rejected', 'MEGA rejected the request.', 502];
    case -8:
      return ['expired', 'That MEGA link has expired.', 410];
    case -9:
      return ['not_found', 'That MEGA link is dead or wrong.', 404];
    case -11:
      return ['access_denied', 'MEGA denied access to that link.', 403];
    case -13:
      return ['incomplete', 'That link is incomplete on MEGA.', 409];
    case -14:
      return ['decrypt_failed', 'The decryption key does not match this link.', 400];
    case -15:
      return ['session_error', 'MEGA rejected the session.', 502];
    case -16:
      return ['blocked', 'MEGA blocked that link.', 403];
    case -17:
    case -24:
      return ['quota_exceeded', 'MEGA transfer quota is exhausted for this link.', 429];
    case -18:
      return ['unavailable', 'MEGA says that link is temporarily unavailable.', 503];
    default:
      return ['mega_error', 'MEGA refused the request.', 502];
  }
}

let sequence = 1 + Math.floor(Math.random() * 999999999);

function nextSequence() {
  sequence = (sequence % 999999999) + 1;
  return String(sequence);
}

async function megaApi({ query = '', body, cmd, count = 1, maxBytes = MAX_API_BYTES }) {
  const id = nextSequence();
  const started = Date.now();
  log('api_request', { cmd, id, count });
  let response;
  try {
    response = await fetch(`${MEGA_API}?id=${id}${query}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new WorkerError('upstream_unreachable', 'MEGA did not answer. Try again.', 502);
  }
  let text;
  try {
    text = await response.text();
  } catch {
    throw new WorkerError('bad_response', 'MEGA returned an unreadable response.', 502);
  }
  log('api_response', {
    cmd,
    status: response.status,
    ms: Date.now() - started,
    bytes: text.length,
  });
  if (response.status === 509) {
    throw new WorkerError('quota_exceeded', 'MEGA transfer quota is exhausted for this link.', 429);
  }
  if (!response.ok) {
    throw new WorkerError('upstream_error', 'MEGA returned an error. Try again.', 502);
  }
  if (text.length > maxBytes) {
    throw new WorkerError('bad_response', 'MEGA returned an oversized response.', 502);
  }
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new WorkerError('bad_response', 'MEGA returned an unreadable response.', 502);
  }
  if (!Array.isArray(payload) || payload.length === 0) {
    throw new WorkerError('bad_response', 'MEGA returned an empty response.', 502);
  }
  const first = payload[0];
  if (typeof first === 'number') {
    const [code, message, status] = mapMegaError(first);
    throw new WorkerError(code, message, status, first);
  }
  return payload;
}

export async function fetchMegaFile(handle) {
  const payload = await megaApi({
    body: [{ a: 'g', g: 1, p: handle, ssl: 2 }],
    cmd: 'g',
  });
  const item = payload[0];
  if (!item || typeof item !== 'object') {
    throw new WorkerError('bad_response', 'MEGA returned an unexpected response.', 502);
  }
  return item;
}

export async function fetchFolderNodes(handle) {
  const payload = await megaApi({
    query: `&n=${encodeURIComponent(handle)}`,
    body: [{ a: 'f', c: 1, r: 1, ca: 1 }],
    cmd: 'f',
  });
  const item = payload[0];
  if (!item || typeof item !== 'object') {
    throw new WorkerError('bad_response', 'MEGA returned an unexpected response.', 502);
  }
  const nodes = Array.isArray(item.f) ? item.f : [];
  if (nodes.length > MAX_FOLDER_NODES) {
    throw new WorkerError('folder_too_large', 'That folder has too many entries.', 413);
  }
  log('folder_nodes', { count: nodes.length });
  return nodes;
}

async function fetchFolderUrls(linkHandle, fileNodes) {
  const urls = new Map();
  for (let start = 0; start < fileNodes.length; start += MAX_BATCH) {
    const chunk = fileNodes.slice(start, start + MAX_BATCH);
    const body = chunk.map((node) => ({ a: 'g', g: 1, n: node.handle, ssl: 2 }));
    const payload = await megaApi({
      query: `&n=${encodeURIComponent(linkHandle)}`,
      body,
      cmd: 'g',
      count: chunk.length,
      maxBytes: MAX_API_BYTES,
    });
    chunk.forEach((node, index) => {
      const item = payload[index];
      if (
        item &&
        typeof item === 'object' &&
        typeof item.g === 'string' &&
        /^https?:\/\//i.test(item.g)
      ) {
        urls.set(node.handle, item.g);
      } else {
        logError('url_error', {
          handle: node.handle,
          megaCode: typeof item === 'number' ? item : null,
        });
      }
    });
  }
  return urls;
}

export function buildFileResult(link, key, item) {
  if (typeof item.g !== 'string' || !/^https?:\/\//i.test(item.g)) {
    throw new WorkerError('bad_response', 'MEGA did not return a download URL.', 502);
  }
  const size = Number(item.s);
  if (!Number.isSafeInteger(size) || size < 0) {
    throw new WorkerError('bad_response', 'MEGA did not return a valid file size.', 502);
  }
  let name = link.handle;
  if (typeof item.at === 'string' && item.at.length > 0) {
    const attrs = decryptAttrs(item.at, key);
    if (typeof attrs.n === 'string' && attrs.n.length > 0) name = attrs.n;
    log('attr_decrypt', { ok: true, cipherChars: item.at.length, nameLength: name.length });
  } else {
    log('attr_decrypt', { ok: false, reason: 'no_attributes' });
  }
  const ext = extensionOf(name);
  log('output', { kind: 'file', size, ext, expiresIn: EXPIRES_IN });
  return {
    kind: 'file',
    name,
    size,
    ext,
    url: item.g,
    expires_in: EXPIRES_IN,
  };
}

export async function buildFolderResult(link, key, nodes, startHandle = null) {
  const { root, files } = buildFolderIndex(nodes, key, startHandle);
  if (files.length > MAX_FOLDER_FILES) {
    throw new WorkerError('folder_too_large', 'That folder has too many files.', 413);
  }
  const urls = await fetchFolderUrls(link.handle, files.map((file) => file.node));
  let total = 0;
  let urlFailures = 0;
  const output = files.map(({ node, path }) => {
    total += node.size;
    const url = urls.get(node.handle) || null;
    if (!url) urlFailures++;
    return {
      path,
      name: node.name,
      size: node.size,
      ext: extensionOf(node.name),
      url,
      expires_in: url ? EXPIRES_IN : null,
    };
  });
  log('output', {
    kind: 'folder',
    files: output.length,
    size: total,
    urlFailures,
    expiresIn: EXPIRES_IN,
  });
  return {
    kind: 'folder',
    name: root.name,
    size: total,
    file_count: output.length,
    files: output,
    expires_in: EXPIRES_IN,
  };
}

export async function buildFolderFileResult(link, key, nodes, fileHandle) {
  const publicRoot = findPublicRoot(nodes);
  const node = nodes.find((item) => item.h === fileHandle);
  if (!node || node.t !== 0) {
    throw new WorkerError('not_found', 'That file is not in this folder.', 404);
  }
  const nodeKey = decryptNodeKey(node, key, publicRoot.h);
  let name = node.h;
  if (typeof node.a === 'string' && node.a.length > 0) {
    const attrs = decryptAttrs(node.a, nodeAttrKey(nodeKey, node.t));
    if (typeof attrs.n === 'string' && attrs.n.length > 0) name = attrs.n;
  }
  const size = Number(node.s);
  if (!Number.isSafeInteger(size) || size < 0) {
    throw new WorkerError('bad_response', 'MEGA sent an invalid file size.', 502);
  }
  const urls = await fetchFolderUrls(link.handle, [{ handle: node.h }]);
  const url = urls.get(node.h);
  if (!url) {
    throw new WorkerError('bad_response', 'MEGA did not return a download URL.', 502);
  }
  const ext = extensionOf(name);
  log('output', { kind: 'file', size, ext, expiresIn: EXPIRES_IN });
  return {
    kind: 'file',
    name,
    size,
    ext,
    url,
    expires_in: EXPIRES_IN,
  };
}

function checkInput(value) {
  if (value.length > MAX_INPUT) {
    throw new WorkerError('invalid_url', 'That link is too long.', 400);
  }
  return value;
}

function inputFromJson(body) {
  if (typeof body === 'string') {
    return { url: body, key: '' };
  }
  if (!body || typeof body !== 'object') {
    throw new WorkerError('bad_request', 'JSON body must be a link or an object with url.', 400);
  }
  const url = typeof body.url === 'string' ? body.url : body.link;
  const key = typeof body.key === 'string' ? body.key : body.k;
  return {
    url: typeof url === 'string' ? url : '',
    key: typeof key === 'string' ? key : '',
  };
}

export async function readInput(request) {
  if (request.method === 'GET') {
    const params = new URL(request.url).searchParams;
    const raw = params.get('url') ?? params.get('link');
    const key = params.get('key') ?? params.get('k') ?? '';
    if (!raw || !raw.trim()) {
      throw new WorkerError(
        'missing_url',
        'Pass a MEGA link as the url query parameter or POST it.',
        400
      );
    }
    return {
      url: checkInput(raw.trim()),
      key: checkInput(key.trim()),
      keySource: key.trim() ? 'param' : 'fragment',
    };
  }
  if (request.method === 'POST') {
    const contentType = (request.headers.get('content-type') || '').toLowerCase();
    if (contentType.includes('application/json')) {
      let body;
      try {
        body = await request.json();
      } catch {
        throw new WorkerError('bad_request', 'POST body must be valid JSON.', 400);
      }
      const input = inputFromJson(body);
      if (!input.url.trim()) {
        throw new WorkerError('missing_url', 'POST body must contain a link.', 400);
      }
      return {
        url: checkInput(input.url.trim()),
        key: checkInput(input.key.trim()),
        keySource: input.key.trim() ? 'param' : 'fragment',
      };
    }
    let text;
    try {
      text = await request.text();
    } catch {
      throw new WorkerError('bad_request', 'Could not read the POST body.', 400);
    }
    if (!text.trim()) {
      throw new WorkerError('missing_url', 'POST body must contain a link.', 400);
    }
    let raw = text.trim();
    let key = '';
    if (contentType.includes('application/x-www-form-urlencoded') && raw.includes('=')) {
      const form = new URLSearchParams(raw);
      raw = (form.get('url') ?? form.get('link') ?? '').trim();
      key = (form.get('key') ?? form.get('k') ?? '').trim();
    }
    if (!raw) {
      throw new WorkerError('missing_url', 'POST body must contain a link.', 400);
    }
    return {
      url: checkInput(raw),
      key: checkInput(key),
      keySource: key ? 'param' : 'fragment',
    };
  }
  throw new WorkerError('method_not_allowed', 'Use GET or POST.', 405);
}

export function parseMegaLink(input, keyParam = '') {
  let parsed;
  try {
    parsed = new URL(input);
  } catch {
    throw new WorkerError('invalid_url', 'That is not a valid link.', 400);
  }
  const host = parsed.hostname.toLowerCase().replace(/^www\./, '');
  if (!ALLOWED_HOSTS.has(host)) {
    throw new WorkerError('invalid_url', 'That is not a MEGA link.', 400);
  }
  const pathParts = parsed.pathname.split('/').filter(Boolean);
  if (pathParts.length < 2) {
    throw new WorkerError('invalid_url', 'Expected a MEGA file or folder link.', 400);
  }
  const kind = pathParts[0].toLowerCase();
  const handle = pathParts[1];
  if (kind !== 'file' && kind !== 'folder') {
    throw new WorkerError('invalid_url', 'Expected a MEGA file or folder link.', 400);
  }
  if (!HANDLE_RE.test(handle)) {
    throw new WorkerError('invalid_url', 'The MEGA handle is malformed.', 400);
  }
  const paramKey = keyParam.startsWith('#') ? keyParam.slice(1) : keyParam;
  const urlKey = parsed.hash.startsWith('#') ? parsed.hash.slice(1) : parsed.hash;
  const fragment = (paramKey || urlKey).trim();
  if (!fragment) {
    throw new WorkerError(
      'missing_key',
      'No key reached the worker. HTTP strips #fragments: send key=<key>, encode # as %23, or POST the raw link.',
      400
    );
  }
  if (fragment.includes('!')) {
    throw new WorkerError('password_protected', 'Password-protected links are not supported.', 400);
  }
  const fragmentParts = fragment.split('/');
  const key = fragmentParts[0];
  let selection = null;
  if (kind === 'folder' && fragmentParts.length >= 3) {
    const selectionType = fragmentParts[1];
    const selectionHandle = fragmentParts[2];
    if (selectionType === 'folder' || selectionType === 'file') {
      if (!HANDLE_RE.test(selectionHandle)) {
        throw new WorkerError('invalid_url', 'The selected MEGA handle is malformed.', 400);
      }
      selection = { type: selectionType, handle: selectionHandle };
    }
  }
  if (kind === 'file') {
    if (!FILE_KEY_RE.test(key)) {
      throw new WorkerError('invalid_key', 'The link decryption key is malformed.', 400);
    }
  } else if (!FOLDER_KEY_RE.test(key)) {
    throw new WorkerError('invalid_key', 'The link decryption key is malformed.', 400);
  }
  return { kind, handle, key, keySource: paramKey ? 'param' : 'fragment', selection };
}
