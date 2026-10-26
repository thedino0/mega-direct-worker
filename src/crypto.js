import { aes128CbcDecrypt } from './aes.js';
import { WorkerError } from './errors.js';

export function b64urlToBytes(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function deriveFileKey(fragment) {
  let raw;
  try {
    raw = b64urlToBytes(fragment);
  } catch {
    throw new WorkerError('invalid_key', 'The link decryption key is malformed.', 400);
  }
  if (raw.length !== 32) {
    throw new WorkerError('invalid_key', 'The link decryption key has the wrong length.', 400);
  }
  const key = new Uint8Array(16);
  for (let i = 0; i < 16; i++) key[i] = raw[i] ^ raw[i + 16];
  return key;
}

export function deriveFolderKey(fragment) {
  let raw;
  try {
    raw = b64urlToBytes(fragment);
  } catch {
    throw new WorkerError('invalid_key', 'The link decryption key is malformed.', 400);
  }
  if (raw.length !== 16) {
    throw new WorkerError('invalid_key', 'The link decryption key has the wrong length.', 400);
  }
  return raw;
}

export function extensionOf(name) {
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return '';
  return name.slice(dot + 1).toLowerCase();
}

export function decryptAttrs(encoded, key) {
  let ciphertext;
  try {
    ciphertext = b64urlToBytes(encoded);
  } catch {
    throw new WorkerError('decrypt_failed', 'MEGA sent metadata we could not decrypt.', 502);
  }
  if (ciphertext.length === 0 || ciphertext.length % 16 !== 0) {
    throw new WorkerError('decrypt_failed', 'MEGA sent metadata we could not decrypt.', 502);
  }
  const plaintext = aes128CbcDecrypt(key, ciphertext);
  if (
    plaintext[0] !== 0x4d ||
    plaintext[1] !== 0x45 ||
    plaintext[2] !== 0x47 ||
    plaintext[3] !== 0x41
  ) {
    throw new WorkerError('decrypt_failed', 'The decryption key does not match this link.', 400);
  }
  let end = plaintext.length;
  while (end > 4 && plaintext[end - 1] === 0) end--;
  let attrs;
  try {
    const text = new TextDecoder().decode(plaintext.subarray(4, end));
    attrs = JSON.parse(text);
  } catch {
    throw new WorkerError('decrypt_failed', 'MEGA sent metadata we could not read.', 502);
  }
  if (!attrs || typeof attrs !== 'object') {
    throw new WorkerError('decrypt_failed', 'MEGA sent metadata we could not read.', 502);
  }
  return attrs;
}

export function nodeAttrKey(nodeKey, type) {
  if (type === 1) return nodeKey;
  const key = new Uint8Array(16);
  for (let i = 0; i < 16; i++) key[i] = nodeKey[i] ^ nodeKey[i + 16];
  return key;
}
