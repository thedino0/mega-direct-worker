function gmul(a, b) {
  let product = 0;
  let left = a;
  let right = b;
  for (let i = 0; i < 8; i++) {
    if (right & 1) product ^= left;
    const high = left & 0x80;
    left = (left << 1) & 0xff;
    if (high) left ^= 0x1b;
    right >>= 1;
  }
  return product & 0xff;
}

function gfPow(base, exponent) {
  if (base === 0) return 0;
  let result = 1;
  let value = base;
  let power = exponent;
  while (power > 0) {
    if (power & 1) result = gmul(result, value);
    value = gmul(value, value);
    power >>= 1;
  }
  return result;
}

function rotl8(value, amount) {
  return ((value << amount) | (value >>> (8 - amount))) & 0xff;
}

const SBOX = new Uint8Array(256);
const INV_SBOX = new Uint8Array(256);

for (let i = 0; i < 256; i++) {
  const inverse = i === 0 ? 0 : gfPow(i, 254);
  const substituted =
    (inverse ^
      rotl8(inverse, 1) ^
      rotl8(inverse, 2) ^
      rotl8(inverse, 3) ^
      rotl8(inverse, 4) ^
      0x63) &
    0xff;
  SBOX[i] = substituted;
  INV_SBOX[substituted] = i;
}

function expandKey(key) {
  const schedule = new Uint8Array(176);
  schedule.set(key);
  let rcon = 1;
  for (let offset = 16; offset < 176; offset += 4) {
    let b0 = schedule[offset - 4];
    let b1 = schedule[offset - 3];
    let b2 = schedule[offset - 2];
    let b3 = schedule[offset - 1];
    if (offset % 16 === 0) {
      const first = b0;
      b0 = SBOX[b1] ^ rcon;
      b1 = SBOX[b2];
      b2 = SBOX[b3];
      b3 = SBOX[first];
      rcon = gmul(rcon, 2);
    }
    schedule[offset] = schedule[offset - 16] ^ b0;
    schedule[offset + 1] = schedule[offset - 15] ^ b1;
    schedule[offset + 2] = schedule[offset - 14] ^ b2;
    schedule[offset + 3] = schedule[offset - 13] ^ b3;
  }
  return schedule;
}

function addRoundKey(state, schedule, offset) {
  for (let i = 0; i < 16; i++) state[i] ^= schedule[offset + i];
}

function invShiftRows(state) {
  const copy = state.slice();
  for (let row = 1; row < 4; row++) {
    for (let column = 0; column < 4; column++) {
      state[row + 4 * ((column + row) % 4)] = copy[row + 4 * column];
    }
  }
}

function invSubBytes(state) {
  for (let i = 0; i < 16; i++) state[i] = INV_SBOX[state[i]];
}

function invMixColumns(state) {
  for (let column = 0; column < 4; column++) {
    const offset = column * 4;
    const a0 = state[offset];
    const a1 = state[offset + 1];
    const a2 = state[offset + 2];
    const a3 = state[offset + 3];
    state[offset] = gmul(a0, 14) ^ gmul(a1, 11) ^ gmul(a2, 13) ^ gmul(a3, 9);
    state[offset + 1] = gmul(a0, 9) ^ gmul(a1, 14) ^ gmul(a2, 11) ^ gmul(a3, 13);
    state[offset + 2] = gmul(a0, 13) ^ gmul(a1, 9) ^ gmul(a2, 14) ^ gmul(a3, 11);
    state[offset + 3] = gmul(a0, 11) ^ gmul(a1, 13) ^ gmul(a2, 9) ^ gmul(a3, 14);
  }
}

function decryptBlock(block, schedule) {
  const state = new Uint8Array(block);
  addRoundKey(state, schedule, 160);
  for (let round = 9; round >= 1; round--) {
    invShiftRows(state);
    invSubBytes(state);
    addRoundKey(state, schedule, round * 16);
    invMixColumns(state);
  }
  invShiftRows(state);
  invSubBytes(state);
  addRoundKey(state, schedule, 0);
  return state;
}

export function aes128CbcDecrypt(key, ciphertext) {
  const schedule = expandKey(key);
  const output = new Uint8Array(ciphertext.length);
  let previous = new Uint8Array(16);
  for (let offset = 0; offset < ciphertext.length; offset += 16) {
    const current = ciphertext.subarray(offset, offset + 16);
    const plain = decryptBlock(current, schedule);
    for (let i = 0; i < 16; i++) output[offset + i] = plain[i] ^ previous[i];
    previous = current;
  }
  return output;
}

export function aes128EcbDecrypt(key, ciphertext) {
  const schedule = expandKey(key);
  const output = new Uint8Array(ciphertext.length);
  for (let offset = 0; offset < ciphertext.length; offset += 16) {
    output.set(decryptBlock(ciphertext.subarray(offset, offset + 16), schedule), offset);
  }
  return output;
}
