import type { ChromeApi } from './chrome-api';

const PROFILE_KEY = 'memstackBrowserProfileId';
const PROFILE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function createBrowserIdentity(chrome: ChromeApi) {
  // A bridge is created once per service-worker boot. Native-port reconnects
  // reuse this instance; the host additionally binds each connection generation.
  const extensionInstanceId = crypto.randomUUID();
  let profile: Promise<string> | undefined;

  async function loadProfile(): Promise<string> {
    const stored = (await chrome.storage.local.get(PROFILE_KEY))[PROFILE_KEY];
    if (typeof stored === 'string' && PROFILE_UUID.test(stored)) return stored.toLowerCase();
    const profileId = crypto.randomUUID();
    // Never announce an ephemeral identity when profile storage is unavailable.
    await chrome.storage.local.set({ [PROFILE_KEY]: profileId });
    return profileId;
  }

  return async () => {
    profile ??= loadProfile().catch((error: unknown) => {
      profile = undefined;
      throw error;
    });
    return { profileId: await profile, extensionInstanceId };
  };
}
