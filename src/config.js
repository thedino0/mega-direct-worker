export const DEBUG = true;
export const EXPIRES_IN = 1200;
export const MEGA_API = 'https://g.api.mega.co.nz/cs';
export const HANDLE_RE = /^[A-Za-z0-9_-]{8}$/;
export const FILE_KEY_RE = /^[A-Za-z0-9_-]{43}$/;
export const FOLDER_KEY_RE = /^[A-Za-z0-9_-]{22}$/;
export const ALLOWED_HOSTS = new Set(['mega.nz', 'mega.io', 'mega.co.nz']);
export const MAX_FOLDER_NODES = 5000;
export const MAX_FOLDER_FILES = 500;
export const MAX_BATCH = 100;
export const MAX_API_BYTES = 8 * 1024 * 1024;
export const MAX_INPUT = 4096;

export const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};
