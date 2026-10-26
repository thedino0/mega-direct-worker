const token = process.env.TELEGRAM_BOT_TOKEN || '';
const workerUrl = process.env.WORKER_URL || '';
const secret = process.env.TELEGRAM_WEBHOOK_SECRET || '';

if (!token || !workerUrl || !secret) {
  console.error('Set TELEGRAM_BOT_TOKEN, WORKER_URL, and TELEGRAM_WEBHOOK_SECRET.');
  process.exit(1);
}

const webhookUrl = `${workerUrl.replace(/\/+$/, '')}/telegram/webhook`;
const response = await fetch(`https://api.telegram.org/bot${token}/setWebhook`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: webhookUrl,
    secret_token: secret,
    allowed_updates: ['message', 'callback_query'],
  }),
});
const result = await response.json().catch(() => null);

if (!response.ok || !result || result.ok !== true) {
  console.error(result && result.description ? result.description : 'setWebhook failed.');
  process.exit(1);
}

console.log(`Webhook set: ${webhookUrl}`);
