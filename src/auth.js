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

export function checkWorkerKey(request, env) {
  const expected = env && env.WORKER_KEY;
  if (typeof expected !== 'string' || expected.length === 0) {
    return {
      ok: false,
      status: 503,
      code: 'worker_key_missing',
      message: 'Worker key is not configured.',
    };
  }
  const provided = request.headers.get('x-key') || '';
  if (!constantTimeEqual(provided, expected)) {
    return {
      ok: false,
      status: 401,
      code: 'unauthorized',
      message: 'Worker key was not accepted.',
    };
  }
  return { ok: true };
}
