import vm from 'node:vm';
import { AsyncLocalStorage } from 'node:async_hooks';
import { createRequire, builtinModules } from 'node:module';
import { realpath, stat } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { formatWithOptions, inspect } from 'node:util';
import { compileCell } from './compiler.mjs';
import { createFacade } from './facade.mjs';
import { managedProcesses } from './processes.mjs';

const ownRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const builtins = new Set(builtinModules.flatMap(name => [name, `node:${name}`]));
const within = (root, path) => path === root || (!relative(root, path).startsWith(`..${sep}`) && relative(root, path) !== '..' && !isAbsolute(relative(root, path)));

function imageMimeType(bytes) {
  if (bytes.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))) return 'image/png';
  if (bytes.subarray(0, 3).equals(Buffer.from('ffd8ff', 'hex'))) return 'image/jpeg';
  if (bytes.subarray(0, 4).equals(Buffer.from('RIFF')) && bytes.subarray(8, 12).equals(Buffer.from('WEBP'))) return 'image/webp';
  throw new Error('image format is unsupported; expected PNG, JPEG or WebP bytes');
}

export class ReplKernel {
  #context;
  #active = null;
  #execution = new AsyncLocalStorage();
  #directories = [];
  #send;
  #invoke;
  #cwd;
  #generation = 0;
  #pending = new Set();

  constructor({ send, rpc, cwd = process.cwd(), enabledSurfaces = ['computer', 'browser'], platform = process.platform }) {
    this.#send = send;
    this.#invoke = rpc;
    this.#cwd = resolve(cwd);
    this.options = { enabledSurfaces, platform };
    this.reset();
  }

  #assertActive() {
    const execution = this.#execution.getStore();
    if (!execution || execution !== this.#active) throw new Error('execution is no longer active');
    return execution;
  }

  #output(content) {
    const execution = this.#assertActive();
    this.#send({ type: 'output', id: execution.id, content });
  }

  #rpc = (method, params) => {
    const execution = this.#assertActive();
    const promise = Promise.resolve(this.#invoke(method, params, execution.id));
    this.#pending.add(promise);
    promise.then(() => this.#pending.delete(promise), () => this.#pending.delete(promise));
    return promise;
  };

  #assertGeneration(generation) {
    if (generation !== this.#generation) throw new Error('REPL handle expired after reset');
  }

  #rpcForGeneration(generation) {
    return (method, params) => {
      this.#assertGeneration(generation);
      return this.#rpc(method, params);
    };
  }

  async addModuleDirectory(path) {
    if (!isAbsolute(path)) throw new TypeError('module directory must be absolute');
    const canonical = await realpath(path);
    if (!(await stat(canonical)).isDirectory()) throw new TypeError('module path is not a directory');
    if (!this.#directories.includes(canonical)) this.#directories.push(canonical);
    return { path: canonical };
  }

  async #import(specifier, generation) {
    this.#assertGeneration(generation);
    if (typeof specifier !== 'string') throw new TypeError('module specifier must be a string');
    if (specifier === 'process' || specifier === 'node:process') throw new Error('process stdio is owned by the REPL transport');
    if (specifier === 'child_process' || specifier === 'node:child_process') {
      const api = managedProcesses(this.#rpcForGeneration(generation));
      return { ...api, default: api };
    }
    if (specifier === '@memstack/cua-repl' || specifier === '@memstack/cua-repl/facade') throw new Error('trusted REPL implementation modules are not user imports');
    if (builtins.has(specifier)) return import(specifier);
    let resolved;
    if (specifier.startsWith('file:')) resolved = fileURLToPath(specifier);
    else if (specifier.startsWith('.') || isAbsolute(specifier)) resolved = resolve(this.#cwd, specifier);
    else {
      for (const base of [this.#cwd, ...this.#directories.map(dirname)]) {
        try { resolved = createRequire(join(base, '__cua_repl__.cjs')).resolve(specifier); break; } catch (error) {
          if (error.code !== 'MODULE_NOT_FOUND') throw error;
        }
      }
      if (!resolved) throw new Error(`cannot resolve module ${JSON.stringify(specifier)}`);
    }
    const canonical = await realpath(resolved);
    if (within(ownRoot, canonical)) throw new Error('trusted REPL implementation modules are not user imports');
    const url = pathToFileURL(canonical);
    // User files refresh after reset. Installed packages retain Node's normal package cache.
    if (!canonical.includes(`${sep}node_modules${sep}`)) url.searchParams.set('replGeneration', String(this.#generation));
    return import(url.href);
  }

  reset() {
    if (this.#active) throw new Error('cannot reset an active execution; terminate the process to cancel');
    this.#generation += 1;
    const generation = this.#generation;
    const rpc = this.#rpcForGeneration(generation);
    const output = content => {
      this.#assertGeneration(generation);
      this.#output(content);
    };
    const write = (value) => output({ type: 'text', text: typeof value === 'string' ? value : inspect(value, { depth: 6, maxArrayLength: 100 }) });
    const emitMedia = (type, value) => {
      this.#assertGeneration(generation);
      const bytes = value?.bytes ?? value?.data ?? value;
      const buffer = typeof bytes === 'string' ? Buffer.from(bytes, 'base64') : Buffer.from(bytes);
      const data = typeof bytes === 'string' ? bytes : buffer.toString('base64');
      // Screenshot APIs return bare bytes. Preserve their encoding; the host
      // independently validates the full image and any explicit MIME claim.
      const mimeType = value?.mimeType ?? (type === 'image' ? imageMimeType(buffer) : 'audio/wav');
      output({ type, mimeType, data });
    };
    const nodeRepl = Object.freeze({ write, emitImage: value => emitMedia('image', value), emitAudio: value => emitMedia('audio', value), env: Object.freeze({}),
      rpc });
    const cua = createFacade({ rpc, write, emitImage: nodeRepl.emitImage, ...this.options });
    const console = Object.freeze(Object.fromEntries(['log', 'info', 'warn', 'error', 'debug', 'dir'].map(level => [level,
      (...args) => write(formatWithOptions({ depth: 6, maxArrayLength: 100 }, ...args))])));
    this.#context = vm.createContext({ cua, nodeRepl, console, Buffer, URL, URLSearchParams, TextEncoder, TextDecoder,
      fetch, Headers, Request, Response, AbortController, AbortSignal, Blob, FormData, crypto: globalThis.crypto,
      setTimeout, clearTimeout, setInterval, clearInterval, setImmediate, clearImmediate, queueMicrotask,
      structuredClone, __cua_import__: specifier => this.#import(specifier, generation) });
    return { generation: this.#generation };
  }

  async execute(id, code, context = {}) {
    if (this.#active) throw new Error('an execution is already active');
    if (typeof id !== 'string' || !id || typeof code !== 'string') throw new TypeError('execute requires string id and code');
    const generation = this.#generation;
    if (context.cwd !== undefined) this.#cwd = resolve(context.cwd);
    // Parse as ESM first so duplicate bindings and invalid syntax fail before partial evaluation.
    new vm.SourceTextModule(code, { context: this.#context });
    const compiled = compileCell(code, `cell-${id}.mjs`);
    const script = new vm.Script(compiled, { filename: `cell-${id}.mjs`, importModuleDynamically: async specifier => {
      const imported = await this.#import(specifier, generation);
      if (imported[Symbol.toStringTag] === 'Module') return imported;
      const module = new vm.SyntheticModule(Object.keys(imported), function () {
        for (const [name, value] of Object.entries(imported)) this.setExport(name, value);
      }, { context: this.#context });
      await module.link(() => {}); await module.evaluate(); return module;
    } });
    const execution = Object.freeze({ id });
    this.#active = execution;
    try {
      return await this.#execution.run(execution, async () => {
        const result = await script.runInContext(this.#context);
        while (this.#pending.size) await Promise.all([...this.#pending]);
        return result;
      });
    } finally { this.#active = null; }
  }
}
