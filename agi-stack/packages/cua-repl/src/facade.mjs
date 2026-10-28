import { nativeSurface } from './native.mjs';
import { browserSurface } from './browser.mjs';
import { browserDocumentation, capabilityDocumentation } from './browser-docs.mjs';

const CORE_DOC = 'CUA: start with getState(), getApp(app), getBrowser({id}), getTab(id,{browser}), or createBrowserTab(browser,url). getBrowser only selects; getTab only binds existing tabs. Read fresh state before choosing element indices. Objects belong to this session and become invalid after reset or authority revocation. Native audio: await cua.computer.audio.start({source:"microphone"}); sources are microphone, system, or mixed; default limit is 60000ms (maximum 300000ms). Stop and save with const receipt=await cua.computer.audio.stop({recording_id:recording.recording_id}), where recording is the start receipt. audio.status({recording_id}) and audio.stop({recording_id}) select one owned recording; omitting the options selects recordings in the current session. Stopping always saves audio. The legacy stop({save:true}) alias is accepted; save:false is unsupported and rejected before dispatch; if receipt.media?.[0]?.inline, nodeRepl.emitAudio(receipt.media[0]); otherwise the saved recording remains available in the desktop recording UI. Locked use: await cua.computer.lockedUse({enabled:true}); the host owns renewal and releases when the active cell finishes, pauses, or stops. Disable with {enabled:false}.';

export function createFacade(options) {
  const { write, enabledSurfaces = ['computer', 'browser'] } = options;
  if (!Array.isArray(enabledSurfaces) || !enabledSurfaces.length || enabledSurfaces.some(s => !['computer', 'browser'].includes(s))) throw new TypeError('enabledSurfaces must contain computer and/or browser');
  const emitted = new Map();
  const document = async (name = 'core', force = false) => {
    const text = name === 'core' ? CORE_DOC : name.startsWith('capability:') ? capabilityDocumentation[name.slice('capability:'.length)] : browserDocumentation;
    if (!text) throw new Error(`documentation is unavailable for ${name}`);
    if (!emitted.has(name) || force) { write(text); emitted.set(name, text); }
    return text;
  };
  const api = {};
  if (enabledSurfaces.includes('computer')) Object.assign(api, nativeSurface(options));
  if (enabledSurfaces.includes('browser')) Object.assign(api, browserSurface({ ...options, document }));
  for (const name of ['getApp', 'getBrowser', 'getTab', 'createBrowserTab']) if (api[name]) {
    const method = api[name];
    api[name] = async (...args) => { await document(); return method(...args); };
  }
  api.getState = async ({ emit = true } = {}) => {
    await document();
    const state = { apps: [], browsers: [] };
    const errors = [];
    if (api.listApps) try { state.apps = await api.listApps({ emit: false }); } catch (error) { errors.push(`computer: ${error.message}`); }
    if (api.listBrowsers) try {
      const browsers = await api.listBrowsers({ emit: false });
      state.browsers = await Promise.all(browsers.map(async browser => ({ ...browser, tabs: await api.listTabs({ browser: browser.id, emit: false }) })));
    } catch (error) { errors.push(`browser: ${error.message}`); }
    if (errors.length) state.errors = errors;
    if (emit) write(state);
    return state;
  };
  api.initialize = () => document();
  api.rewriteDocumentation = async () => { if (!emitted.size) await document(); else for (const text of emitted.values()) write(text); };
  return Object.freeze(api);
}
