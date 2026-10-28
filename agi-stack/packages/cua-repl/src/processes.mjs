import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { promisify } from 'node:util';

/** Node-compatible asynchronous process conveniences; the host owns every OS process. */
export function managedProcesses(rpc) {
  const spawn = (executable, args = [], options = {}) => {
    if (!Array.isArray(args)) { options = args; args = []; }
    if (typeof executable !== 'string' || args.some(arg => typeof arg !== 'string')) throw new TypeError('spawn requires an executable and string arguments');
    if (options.detached || options.shell) throw new Error('detached and implicit shell processes are unavailable');
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.exitCode = null; child.signalCode = null; child.killed = false;
    const input = [];
    child.stdin = new Writable({ write(chunk, _encoding, callback) { input.push(Buffer.from(chunk)); callback(); } });
    child.kill = () => { throw new Error('cancel the active execution to terminate its managed processes'); };
    child.ref = () => child; child.unref = () => child;
    queueMicrotask(async () => {
      try {
        const result = await rpc('process.spawn', { executable, args, ...(options.cwd ? { cwd: String(options.cwd) } : {}),
          ...(options.env ? { env: options.env } : {}), ...(options.timeout ? { timeoutMs: options.timeout } : {}),
          ...(input.length ? { input: Buffer.concat(input).toString('utf8') } : {}) });
        child.stdout.end(result.stdout ?? ''); child.stderr.end(result.stderr ?? '');
        child.exitCode = result.exitCode; child.signalCode = result.signal ?? null;
        child.emit('exit', child.exitCode, child.signalCode); child.emit('close', child.exitCode, child.signalCode);
      } catch (error) { child.stdout.end(); child.stderr.end(); child.emit('error', error); child.emit('close', null, null); }
    });
    return child;
  };
  const execFile = (file, args, options, callback) => {
    if (typeof args === 'function') { callback = args; args = []; options = {}; }
    else if (!Array.isArray(args)) { callback = typeof options === 'function' ? options : callback; options = args ?? {}; args = []; }
    if (typeof options === 'function') { callback = options; options = {}; }
    const child = spawn(file, args, options ?? {});
    let stdout = ''; let stderr = ''; let failed = false;
    child.stdout.on('data', data => { stdout += data; }); child.stderr.on('data', data => { stderr += data; });
    child.on('error', error => { failed = true; callback?.(error, stdout, stderr); });
    child.on('close', code => {
      if (failed) return;
      const error = code === 0 ? null : Object.assign(new Error(`process exited with code ${code}`), { code, stdout, stderr });
      callback?.(error, stdout, stderr);
    });
    return child;
  };
  const exec = (command, options, callback) => {
    if (typeof options === 'function') { callback = options; options = {}; }
    return execFile('/bin/sh', ['-c', command], options ?? {}, callback);
  };
  for (const method of [exec, execFile]) method[promisify.custom] = (...args) => new Promise((resolve, reject) => method(...args, (error, stdout, stderr) => error ? reject(error) : resolve({ stdout, stderr })));
  const unsupported = () => { throw new Error('synchronous child processes cannot use the asynchronous host broker'); };
  return Object.freeze({ spawn, exec, execFile, fork: (file, args = [], options = {}) => spawn(options.execPath ?? process.execPath, [file, ...args], options),
    spawnSync: unsupported, execSync: unsupported, execFileSync: unsupported });
}
