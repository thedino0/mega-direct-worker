import {
  FILE_KEY_RE,
  FOLDER_KEY_RE,
  HANDLE_RE,
  MAX_FOLDER_FILES,
} from './config.js';
import { WorkerError } from './errors.js';
import { log, logError } from './log.js';
import { deriveFileKey, deriveFolderKey } from './crypto.js';
import {
  buildFileResult,
  buildFolderFileResult,
  buildFolderIndex,
  fetchFolderNodes,
  fetchMegaFile,
  parseMegaLink,
} from './mega.js';
import { jsonResponse } from './http.js';

const PAGE_SIZE = 6;
const SPEED_SAMPLE_BYTES = 1024 * 1024;
const WELCOME =
  'Send a public MEGA file or folder link.\nFolder links show the file list, sizes, and total size. Pick a file to get a direct link and a speed test.';

function constantTimeEqual(left, right) {
  if (typeof left !== 'string' || typeof right !== 'string' || left.length !== right.length) {
    return false;
  }
  let difference = 0;
  for (let i = 0; i < left.length; i++) {
    difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return difference === 0;
}

async function telegramApi(env, method, payload) {
  const token = env && env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    throw new WorkerError('telegram_not_configured', 'Telegram is not configured on this worker.', 503);
  }
  const started = Date.now();
  let response;
  try {
    response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new WorkerError('telegram_unreachable', 'Telegram did not answer.', 502);
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new WorkerError('telegram_bad_response', 'Telegram returned an unreadable response.', 502);
  }
  log('tg_api', {
    method,
    status: response.status,
    ms: Date.now() - started,
    ok: Boolean(data && data.ok === true),
  });
  if (!response.ok || !data || data.ok !== true) {
    const description =
      data && typeof data.description === 'string'
        ? data.description
        : 'Telegram rejected the request.';
    throw new WorkerError('telegram_error', description, 502);
  }
  return data.result;
}

function truncate(value, length) {
  const text = String(value);
  if (text.length <= length) return text;
  return `${text.slice(0, Math.max(0, length - 3))}...`;
}

function cleanName(value) {
  const text = String(value || 'File').replace(/\s+/g, ' ').trim();
  return text || 'File';
}

function formatBytes(value) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = Number(value) || 0;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  const digits = unit === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(digits)} ${units[unit]}`;
}

function formatSpeed(mbps) {
  const value = Number(mbps) || 0;
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} MB/s`;
}

function sendMessage(env, chatId, text, keyboard = null) {
  const payload = {
    chat_id: chatId,
    text: truncate(text, 3900),
    disable_web_page_preview: true,
  };
  if (Array.isArray(keyboard)) payload.reply_markup = { inline_keyboard: keyboard };
  return telegramApi(env, 'sendMessage', payload);
}

function editMessageText(env, chatId, messageId, text, keyboard = null) {
  const payload = {
    chat_id: chatId,
    message_id: messageId,
    text: truncate(text, 3900),
    disable_web_page_preview: true,
  };
  if (Array.isArray(keyboard)) payload.reply_markup = { inline_keyboard: keyboard };
  return telegramApi(env, 'editMessageText', payload);
}

function answerCallbackQuery(env, id, text = '', showAlert = false) {
  return telegramApi(env, 'answerCallbackQuery', {
    callback_query_id: id,
    text: truncate(text, 190),
    show_alert: showAlert,
  });
}

function publicError(error) {
  if (error instanceof WorkerError) return error.message;
  return 'Something broke while resolving that link.';
}

function folderMenu(folderHandle, folderKey, startHandle, page, index) {
  const total = index.files.reduce((sum, file) => sum + file.node.size, 0);
  const totalPages = Math.max(1, Math.ceil(index.files.length / PAGE_SIZE));
  const safePage = Math.min(Math.max(0, page), totalPages - 1);
  const offset = safePage * PAGE_SIZE;
  const visible = index.files.slice(offset, offset + PAGE_SIZE);
  const rows = visible.map((file) => [
    {
      text: truncate(`${file.path} - ${formatBytes(file.node.size)}`, 60),
      callback_data: ['d', folderHandle, folderKey, startHandle, file.node.handle].join(':'),
    },
  ]);
  if (totalPages > 1) {
    const navigation = [];
    if (safePage > 0) {
      navigation.push({
        text: 'Prev',
        callback_data: ['p', folderHandle, folderKey, startHandle, String(safePage - 1)].join(':'),
      });
    }
    if (safePage < totalPages - 1) {
      navigation.push({
        text: 'Next',
        callback_data: ['p', folderHandle, folderKey, startHandle, String(safePage + 1)].join(':'),
      });
    }
    rows.push(navigation);
  }
  const lines = [
    `Folder: ${cleanName(index.root.name)}`,
    `Files: ${index.files.length} - Total: ${formatBytes(total)}`,
    `Page ${safePage + 1}/${totalPages}`,
    '',
  ];
  if (index.files.length === 0) lines.push('This folder is empty.');
  else lines.push('Choose a file:');
  return { text: lines.join('\n'), keyboard: rows, page: safePage };
}

function fileText(file) {
  const lines = [
    cleanName(file.name),
    `Size: ${formatBytes(file.size)}`,
  ];
  if (file.ext) lines.push(`Type: ${file.ext.toUpperCase()}`);
  if (file.url) lines.push('Direct link expires in about 20 minutes.');
  else lines.push('Direct link is unavailable.');
  return lines.join('\n');
}

function fileKeyboard(file, speedData, backData) {
  const rows = [];
  if (file.url) rows.push([{ text: 'Download', url: file.url }]);
  if (file.url && speedData) {
    rows.push([{ text: 'Speed test', callback_data: speedData }]);
  }
  if (backData) {
    rows.push([{ text: 'Back to files', callback_data: backData }]);
  }
  return rows;
}

function speedText(file, sample) {
  return [
    cleanName(file.name),
    `Size: ${formatBytes(file.size)}`,
    `MEGA speed: ${formatSpeed(sample.mbps)}`,
    `Sample: ${formatBytes(sample.bytes)} in ${sample.ms} ms`,
    'Measured from the worker to MEGA, not your device.',
  ].join('\n');
}

function parseCallback(data) {
  if (typeof data !== 'string') return null;
  const parts = data.split(':');
  if (parts[0] === 'p' && parts.length === 5) {
    const [, folderHandle, folderKey, startHandle, pageText] = parts;
    if (!HANDLE_RE.test(folderHandle) || !FOLDER_KEY_RE.test(folderKey)) return null;
    if (startHandle !== '0' && !HANDLE_RE.test(startHandle)) return null;
    const page = Number(pageText);
    if (!Number.isInteger(page) || page < 0 || page > 10000) return null;
    return { action: 'p', folderHandle, folderKey, startHandle, page };
  }
  if (parts[0] === 'd' && parts.length === 5) {
    const [, folderHandle, folderKey, startHandle, fileHandle] = parts;
    if (!HANDLE_RE.test(folderHandle) || !FOLDER_KEY_RE.test(folderKey)) return null;
    if (startHandle !== '0' && !HANDLE_RE.test(startHandle)) return null;
    if (!HANDLE_RE.test(fileHandle)) return null;
    return { action: 'd', folderHandle, folderKey, startHandle, fileHandle };
  }
  if (parts[0] === 's' && parts.length === 3) {
    const [, fileHandle, fileKey] = parts;
    if (!HANDLE_RE.test(fileHandle) || !FILE_KEY_RE.test(fileKey)) return null;
    return { action: 's', direct: true, fileHandle, fileKey };
  }
  if (parts[0] === 's' && parts.length === 5) {
    const [, folderHandle, folderKey, startHandle, fileHandle] = parts;
    if (!HANDLE_RE.test(folderHandle) || !FOLDER_KEY_RE.test(folderKey)) return null;
    if (startHandle !== '0' && !HANDLE_RE.test(startHandle)) return null;
    if (!HANDLE_RE.test(fileHandle)) return null;
    return {
      action: 's',
      direct: false,
      folderHandle,
      folderKey,
      startHandle,
      fileHandle,
    };
  }
  return null;
}

function extractLink(text) {
  const match = String(text).match(/https?:\/\/[^\s]+/i);
  if (!match) return '';
  return match[0].replace(/[),.;]+$/, '');
}

async function requestFolder(link) {
  const key = deriveFolderKey(link.key);
  const nodes = await fetchFolderNodes(link.handle);
  return { key, nodes };
}

async function sendFolderMenu(env, chatId, link, key, nodes, startHandle, page) {
  const index = buildFolderIndex(nodes, key, startHandle === '0' ? null : startHandle);
  if (index.files.length > MAX_FOLDER_FILES) {
    throw new WorkerError('folder_too_large', 'That folder has too many files.', 413);
  }
  const menu = folderMenu(link.handle, link.key, startHandle, page, index);
  await sendMessage(env, chatId, menu.text, menu.keyboard);
}

async function sendFolderFile(env, chatId, link, key, nodes, fileHandle, startHandle) {
  const file = await buildFolderFileResult(link, key, nodes, fileHandle);
  const speedData = ['s', link.handle, link.key, startHandle, fileHandle].join(':');
  const backData = ['p', link.handle, link.key, startHandle, '0'].join(':');
  await sendMessage(env, chatId, fileText(file), fileKeyboard(file, speedData, backData));
}

async function sendDirectFile(env, chatId, link) {
  const key = deriveFileKey(link.key);
  const item = await fetchMegaFile(link.handle);
  const file = buildFileResult(link, key, item);
  const speedData = ['s', link.handle, link.key].join(':');
  await sendMessage(env, chatId, fileText(file), fileKeyboard(file, speedData, null));
}

async function handleMessage(message, env) {
  const chatId = message.chat && message.chat.id;
  const text = typeof message.text === 'string' ? message.text.trim() : '';
  if (!chatId || !text) return;
  if (text === '/start' || text === '/help') {
    await sendMessage(env, chatId, WELCOME);
    return;
  }
  const linkText = extractLink(text);
  if (!linkText) {
    await sendMessage(env, chatId, WELCOME);
    return;
  }
  log('tg_message', { kind: 'link' });
  try {
    const link = parseMegaLink(linkText);
    if (link.kind === 'file') {
      await sendDirectFile(env, chatId, link);
      return;
    }
    const { key, nodes } = await requestFolder(link);
    if (link.selection && link.selection.type === 'file') {
      await sendFolderFile(env, chatId, link, key, nodes, link.selection.handle, '0');
      return;
    }
    const startHandle =
      link.selection && link.selection.type === 'folder' ? link.selection.handle : '0';
    await sendFolderMenu(env, chatId, link, key, nodes, startHandle, 0);
  } catch (error) {
    logError('tg_message_error', {
      code: error instanceof WorkerError ? error.code : 'internal',
      message: error instanceof Error ? error.message : String(error),
    });
    await sendMessage(env, chatId, `Error: ${publicError(error)}`).catch(() => {});
  }
}

async function handleCallback(query, env) {
  const chatId = query.message && query.message.chat ? query.message.chat.id : null;
  const messageId = query.message ? query.message.message_id : null;
  const data = parseCallback(query.data);
  await answerCallbackQuery(env, query.id).catch((error) => {
    logError('tg_answer_error', {
      code: error instanceof WorkerError ? error.code : 'internal',
    });
  });
  if (!chatId || !messageId || !data) {
    if (chatId) {
      await sendMessage(env, chatId, 'This button is invalid or expired.').catch(() => {});
    }
    return;
  }
  log('tg_callback', { action: data.action });
  try {
    if (data.action === 'p') {
      const link = { handle: data.folderHandle, key: data.folderKey };
      const { key, nodes } = await requestFolder(link);
      const index = buildFolderIndex(
        nodes,
        key,
        data.startHandle === '0' ? null : data.startHandle
      );
      if (index.files.length > MAX_FOLDER_FILES) {
        throw new WorkerError('folder_too_large', 'That folder has too many files.', 413);
      }
      const menu = folderMenu(data.folderHandle, data.folderKey, data.startHandle, data.page, index);
      await editMessageText(env, chatId, messageId, menu.text, menu.keyboard);
      return;
    }
    if (data.action === 'd') {
      const link = { handle: data.folderHandle, key: data.folderKey };
      const { key, nodes } = await requestFolder(link);
      const file = await buildFolderFileResult(link, key, nodes, data.fileHandle);
      const speedData = ['s', data.folderHandle, data.folderKey, data.startHandle, data.fileHandle].join(':');
      const backData = ['p', data.folderHandle, data.folderKey, data.startHandle, '0'].join(':');
      await editMessageText(env, chatId, messageId, fileText(file), fileKeyboard(file, speedData, backData));
      return;
    }
    let file;
    if (data.direct) {
      const key = deriveFileKey(data.fileKey);
      const item = await fetchMegaFile(data.fileHandle);
      file = buildFileResult({ handle: data.fileHandle }, key, item);
    } else {
      const link = { handle: data.folderHandle, key: data.folderKey };
      const { key, nodes } = await requestFolder(link);
      file = await buildFolderFileResult(link, key, nodes, data.fileHandle);
    }
    const sample = await measureSpeed(file.url);
    const speedData = data.direct
      ? ['s', data.fileHandle, data.fileKey].join(':')
      : ['s', data.folderHandle, data.folderKey, data.startHandle, data.fileHandle].join(':');
    const keyboard = file.url
      ? [
          [{ text: 'Download', url: file.url }],
          [{ text: 'Speed test again', callback_data: speedData }],
        ]
      : [];
    await sendMessage(env, chatId, speedText(file, sample), keyboard);
  } catch (error) {
    logError('tg_callback_error', {
      code: error instanceof WorkerError ? error.code : 'internal',
      message: error instanceof Error ? error.message : String(error),
    });
    await sendMessage(env, chatId, `Error: ${publicError(error)}`).catch(() => {});
  }
}

export async function processTelegramUpdate(update, env) {
  try {
    if (update.message) {
      await handleMessage(update.message, env);
      return;
    }
    if (update.callback_query) {
      await handleCallback(update.callback_query, env);
    }
  } catch (error) {
    logError('tg_update_error', {
      code: error instanceof WorkerError ? error.code : 'internal',
      message: error instanceof Error ? error.message : String(error),
    });
  }
}

async function measureSpeed(url) {
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) {
    throw new WorkerError('speed_failed', 'No direct URL is available for a speed test.', 400);
  }
  const started = Date.now();
  let response;
  try {
    response = await fetch(url, {
      headers: { Range: `bytes=0-${SPEED_SAMPLE_BYTES - 1}` },
    });
  } catch {
    throw new WorkerError('speed_failed', 'Could not reach MEGA for the speed test.', 502);
  }
  if (!response.ok && response.status !== 206) {
    throw new WorkerError('speed_failed', 'MEGA refused the speed test request.', 502);
  }
  let bytes = 0;
  if (response.body) {
    const reader = response.body.getReader();
    try {
      while (bytes < SPEED_SAMPLE_BYTES) {
        const chunk = await reader.read();
        if (chunk.done) break;
        bytes += chunk.value.byteLength;
      }
    } finally {
      try {
        await reader.cancel();
      } catch {}
    }
  } else {
    const buffer = await response.arrayBuffer();
    bytes = buffer.byteLength;
  }
  const ms = Math.max(1, Date.now() - started);
  if (bytes === 0) {
    throw new WorkerError('speed_failed', 'MEGA returned no data for the speed test.', 502);
  }
  return { bytes, ms, mbps: bytes / 1048576 / (ms / 1000) };
}

export async function handleTelegramWebhook(request, env) {
  const token = env && env.TELEGRAM_BOT_TOKEN;
  const secret = env && env.TELEGRAM_WEBHOOK_SECRET;
  if (!token || !secret) {
    return jsonResponse(
      {
        error: {
          code: 'telegram_not_configured',
          message: 'Telegram is not configured on this worker.',
        },
      },
      503
    );
  }
  const supplied = request.headers.get('x-telegram-bot-api-secret-token') || '';
  if (!constantTimeEqual(supplied, secret)) {
    return jsonResponse(
      { error: { code: 'unauthorized', message: 'Invalid webhook secret.' } },
      401
    );
  }
  let update;
  try {
    update = await request.json();
  } catch {
    return jsonResponse(
      { error: { code: 'bad_request', message: 'Invalid Telegram update.' } },
      400
    );
  }
  if (!update || typeof update !== 'object') {
    return jsonResponse(
      { error: { code: 'bad_request', message: 'Invalid Telegram update.' } },
      400
    );
  }
  log('tg_update', {
    message: Boolean(update.message),
    callback: Boolean(update.callback_query),
  });
  await processTelegramUpdate(update, env);
  return jsonResponse({ ok: true });
}
