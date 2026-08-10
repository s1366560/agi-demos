import { defineConfig } from 'wxt';

// The `key` pins the extension ID to enbljdpbhdllbbkcjhccmbgpkfmcdkkl so the
// desktop sidecar can register its native messaging host against a stable ID.
const EXTENSION_KEY =
  'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1+W+/+omDm4fWP8D6WquWUhLGPs4LJnf7cjk20gdWajGOMW+7gmlynTCc+loFWDah1koQYfbmqSVF2VR8amGuwEfyKeAZQaTuqABQbMWKoOfVY7SQysKJILQUKc+CfvYt0V5c0JmHatsb5s+/LaRPM8ED4oRi69/U695QFasSILDyWCclNumhXZ9LnF2jktC5Y+eKJ1OsolbjDU8C09q6ZU7VibQe/1qMKfkie1wXPYQ7ZZ/6ydlcD33RVcHZN2vbUbKtW3W8hTtGdQx6/8LGKRGhk4CMDFbSs3+84D0Vm0f3Qa37liFZ8KZTns/2JO7Y36ThysZGyiy2mKcq9cAYwIDAQAB';

export default defineConfig({
  manifest: {
    name: 'MemStack Browser Bridge',
    description: 'Lets the MemStack desktop app read and drive your browser tabs.',
    version: '0.1.0',
    key: EXTENSION_KEY,
    minimum_chrome_version: '116',
    permissions: ['alarms', 'debugger', 'nativeMessaging', 'scripting', 'storage', 'tabGroups', 'tabs'],
    host_permissions: ['<all_urls>'],
  },
});
