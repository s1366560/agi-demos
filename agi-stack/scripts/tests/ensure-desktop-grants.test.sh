#!/bin/sh
# Executable offline contract tests. Every subprocess runs in a disposable repo
# with curl, bootstrap Python, pnpm, cargo and the final launcher replaced.
set -eu
exec python3 - "$0" "$@" <<'PY'
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

test_file = Path(sys.argv[1]).resolve()
script_source = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else test_file.parents[1] / 'ensure-desktop-grants.sh'
make_source = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else test_file.parents[2] / 'Makefile'
origin = 'http://127.0.0.1:18081'
prefixes = ('AGISTACK_PLUGIN_DATA_PLANE', 'AGISTACK_PLUGIN_RENDERER_DATA_PLANE')
keys = [prefix + '_' + suffix for prefix in prefixes for suffix in
        ('CREDENTIAL_V2', 'API_BASE_URL_V2', 'ACK_PARTICIPATION_V2')]
tokens = ('ms_dp_' + 'a' * 64, 'ms_dp_' + 'b' * 64)

stub = r'''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
log = pathlib.Path(os.environ['STUB_LOG'])
tokens = ('ms_dp_' + 'a' * 64, 'ms_dp_' + 'b' * 64)
prefixes = ('AGISTACK_PLUGIN_DATA_PLANE', 'AGISTACK_PLUGIN_RENDERER_DATA_PLANE')
def record(data):
    with log.open('a') as stream: stream.write(json.dumps(data) + '\n')
if name == 'curl':
    url = next((arg for arg in reversed(args) if arg.startswith(('http://', 'https://'))), '')
    if url.endswith('/docs'):
        record({'kind':'docs', 'url':url})
        sys.exit(int(os.environ.get('STUB_DOCS_EXIT', '0')))
    if not url.endswith('/api/v1/platform-plugins/v2/distribution'):
        record({'kind':'unexpected_curl'}); sys.exit(97)
    config = sys.stdin.read() if '--config' in args and args[args.index('--config') + 1] == '-' else ''
    joined = '\n'.join(args)
    role = 'sidecar' if tokens[0] in config + joined else 'renderer' if tokens[1] in config + joined else 'unknown'
    record({'kind':'probe', 'role':role, 'url':url, 'stdin_header':bool(config),
            'secret_in_argv':any(token in joined for token in tokens)})
    events = [json.loads(line) for line in log.read_text().splitlines()]
    if os.environ.get('STUB_REWRITE_AFTER_PROBE') == '1' and sum(e['kind'] == 'probe' for e in events) == 2:
        pathlib.Path(os.environ['STUB_ENV_FILE']).write_text('invalid rewritten file\n')
        record({'kind':'rewrite'})
    print(os.environ.get('STUB_' + role.upper() + '_STATUS', '200'), end='')
    sys.exit(int(os.environ.get('STUB_' + role.upper() + '_EXIT', '0')))
if name == 'python':
    record({'kind':'bootstrap'})
    code = int(os.environ.get('STUB_BOOTSTRAP_EXIT', '0'))
    if code: sys.exit(code)
    def value(flag): return args[args.index(flag) + 1]
    lines = []
    for prefix, token in zip(prefixes, tokens):
        lines.extend(('export ' + prefix + '_CREDENTIAL_V2=' + token,
                      'export ' + prefix + '_API_BASE_URL_V2=' + value('--api-base'),
                      'export ' + prefix + '_ACK_PARTICIPATION_V2=true'))
    pathlib.Path(value('--output')).write_text('\n'.join(lines) + '\n')
    pathlib.Path(value('--metadata-output')).write_text('{"grants": []}\n')
    sys.exit(0)
if name == 'cargo': record({'kind':'cargo'}); sys.exit(0)
if name == 'pnpm' and args != ['run', 'dev:electron']:
    record({'kind':'pnpm_build_stub'}); sys.exit(0)
if name in ('launch', 'pnpm'):
    grant_keys = [p + '_' + s for p in prefixes for s in
                  ('CREDENTIAL_V2', 'API_BASE_URL_V2', 'ACK_PARTICIPATION_V2')]
    absent = all(key not in os.environ for key in grant_keys)
    pair_ok = all(os.environ.get(p + '_CREDENTIAL_V2') == token and
                  os.environ.get(p + '_API_BASE_URL_V2') == os.environ['STUB_EXPECT_ORIGIN'] and
                  os.environ.get(p + '_ACK_PARTICIPATION_V2') == os.environ.get('STUB_EXPECT_ACK_' + str(i), 'true')
                  for i, (p, token) in enumerate(zip(prefixes, tokens)))
    record({'kind':'launch', 'pair_ok':pair_ok, 'all_grants_absent':absent,
            'present_grant_keys':sorted(key for key in grant_keys if key in os.environ),
            'args':args, 'cwd':os.getcwd()})
    sys.exit(int(os.environ.get('STUB_LAUNCH_EXIT', '0')))
record({'kind':'unexpected_stub'}); sys.exit(98)
'''

def require(condition, message):
    if not condition:
        raise AssertionError(message)

class Fixture:
    def __init__(self, label):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop-grants-offline-' + label + '-')
        self.root = Path(self.temp.name)
        self.agi = self.root / 'agi-stack'
        self.app = self.agi / 'apps/desktop'
        self.bin = self.root / 'fake-bin'
        self.grants = self.root / 'configured grants'
        self.log = self.root / 'events.jsonl'
        for path in (self.app, self.bin, self.grants, self.agi / 'scripts', self.root / '.venv/bin'):
            path.mkdir(parents=True, exist_ok=True)
        self.script = self.agi / 'scripts/ensure-desktop-grants.sh'
        shutil.copyfile(script_source, self.script)
        self.script.chmod(0o755)
        shutil.copyfile(make_source, self.agi / 'Makefile')
        (self.agi / 'offline.mk').write_text('desktop-deps desktop-cua-helper desktop-cua-repl:\n\t@:\n')
        executable = '#!' + sys.executable + '\n' + stub
        for name in ('curl', 'pnpm', 'cargo', 'launch'):
            path = self.bin / name
            path.write_text(executable)
            path.chmod(0o755)
        path = self.root / '.venv/bin/python'
        path.write_text(executable)
        path.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in keys and not key.startswith(('AGISTACK_DESKTOP_GRANTS_', 'STUB_'))}
        self.env.update(PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        AGISTACK_DESKTOP_GRANTS_API_BASE=origin,
                        AGISTACK_DESKTOP_GRANTS_DIR=str(self.grants),
                        AGISTACK_DESKTOP_GRANTS_REUSE_ONLY='1',
                        STUB_LOG=str(self.log), STUB_ENV_FILE=str(self.grants / 'grants.env'),
                        STUB_EXPECT_ORIGIN=origin)
    def close(self):
        self.temp.cleanup()
    def values(self):
        return {prefix + '_' + suffix: value
                for prefix, token in zip(prefixes, tokens)
                for suffix, value in (('CREDENTIAL_V2', token), ('API_BASE_URL_V2', origin),
                                      ('ACK_PARTICIPATION_V2', 'true'))}
    def write(self, values=None, quoted=False, extra=''):
        values = self.values() if values is None else values
        self.grants.mkdir(parents=True, exist_ok=True)
        path = self.grants / 'grants.env'
        path.write_text(''.join('export ' + key + '=' + ("'" + value + "'" if quoted else value) + '\n'
                                for key, value in values.items()) + extra)
        path.chmod(0o600)
        return path
    def events(self, kind=None):
        events = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return [event for event in events if kind is None or event['kind'] == kind]
    def run(self, make=False, standalone=False):
        if make:
            command = ['make', '--no-print-directory', '-f', 'Makefile', '-f', 'offline.mk',
                       'run-desktop', 'CARGO=' + str(self.bin / 'cargo'), 'PNPM=' + str(self.bin / 'pnpm')]
            cwd = self.agi
        else:
            command = [str(self.script)] if standalone else [str(self.script), '--', str(self.bin / 'launch'), 'argument with spaces', 'last']
            cwd = self.app
        result = subprocess.run(command, cwd=cwd, env=self.env, capture_output=True, text=True, timeout=20)
        require(not any(token in result.stdout + result.stderr for token in tokens), 'credential appeared in process output')
        require(not any(event.get('secret_in_argv') for event in self.events()), 'credential entered curl argv')
        require(not any(event['kind'].startswith('unexpected') for event in self.events()), 'unexpected stub invocation')
        return result
    def fail_closed(self, expect_no_curl=False):
        path = self.grants / 'grants.env'
        before = path.read_bytes() if path.exists() else None
        result = self.run()
        require(result.returncode == 1, 'reuse failure did not return exit 1')
        require(not self.events('bootstrap') and not self.events('launch'), 'reuse failure bootstrapped or launched')
        require((path.read_bytes() if path.exists() else None) == before, 'reuse failure changed grant file')
        if expect_no_curl:
            require(not self.events('docs') and not self.events('probe'), 'structural refusal reached curl')
    def launched(self, local=False):
        events = self.events('launch')
        require(len(events) == 1, 'expected exactly one launch')
        require(events[0]['all_grants_absent'] if local else events[0]['pair_ok'], 'launcher received wrong grant environment')
        if not local:
            require(events[0]['present_grant_keys'] == sorted(keys), 'launcher did not receive the six grant exports')

def case_missing(f):
    f.fail_closed(expect_no_curl=True)

def case_inherited(f):
    f.env.update(f.values())
    f.fail_closed(expect_no_curl=True)

def invalid_values(f, change):
    values = f.values()
    change(values)
    f.write(values)
    f.fail_closed(expect_no_curl=True)

def invalid_text(f, text):
    f.write(extra=text)
    f.fail_closed(expect_no_curl=True)

def case_command(f):
    marker = f.root / 'must-not-execute'
    f.write(extra='touch ' + shlex.quote(str(marker)) + '\n')
    f.fail_closed(expect_no_curl=True)
    require(not marker.exists(), 'grant file was executed as shell code')

def case_force(f):
    f.write()
    f.env['AGISTACK_DESKTOP_GRANTS_FORCE'] = '1'
    f.fail_closed(expect_no_curl=True)

def case_bad_origin(f, value):
    values = f.values()
    values[keys[1]] = value
    values[keys[4]] = value
    f.env['AGISTACK_DESKTOP_GRANTS_API_BASE'] = value
    f.write(values)
    f.fail_closed(expect_no_curl=True)

def case_ipv6(f):
    value = 'http://[::1]:18081'
    values = f.values()
    values[keys[1]] = value + '/'
    values[keys[4]] = value
    f.env.update(AGISTACK_DESKTOP_GRANTS_API_BASE=value + '/', STUB_EXPECT_ORIGIN=value)
    f.write(values, quoted=True)
    require(f.run().returncode == 0, 'quoted IPv6 loopback origin failed')
    f.launched()
    require([event['role'] for event in f.events('probe')] == ['sidecar', 'renderer'], 'IPv6 pair was not probed')

def case_down(f):
    f.write()
    f.env['STUB_DOCS_EXIT'] = '7'
    f.fail_closed()
    require(not f.events('probe'), 'unreachable health check still probed secrets')

def case_rejected(f, role, code='401', exit_code='0'):
    f.write()
    f.env.update({'STUB_' + role + '_STATUS': code, 'STUB_' + role + '_EXIT': exit_code})
    f.fail_closed()

def case_valid(f, mixed=False):
    values = f.values()
    if mixed:
        values[keys[2]] = 'false'
        f.env.update(STUB_EXPECT_ACK_0='false', STUB_RENDERER_STATUS='404',
                     AGISTACK_DESKTOP_GRANTS_API_BASE=origin + '/')
    path = f.write(values, quoted=mixed)
    before = path.read_bytes()
    result = f.run()
    require(result.returncode == 0, 'valid pair failed')
    f.launched()
    require([event['role'] for event in f.events('probe')] == ['sidecar', 'renderer'], 'both credentials were not probed')
    require(all(event['stdin_header'] for event in f.events('probe')), 'curl did not read credential headers from stdin')
    require(not f.events('bootstrap') and path.read_bytes() == before, 'valid reuse mutated or bootstrapped')
    require(f.events('launch')[0]['args'] == ['argument with spaces', 'last'], 'launch arguments lost boundaries')

def case_default_mint(f, invalid=False, force=False):
    f.env['AGISTACK_DESKTOP_GRANTS_REUSE_ONLY'] = '0'
    if invalid: f.write(extra='invalid syntax\n')
    if force:
        f.write()
        f.env['AGISTACK_DESKTOP_GRANTS_FORCE'] = '1'
    require(f.run().returncode == 0, 'default provisioning failed')
    require(len(f.events('bootstrap')) == 1, 'default mode did not provision exactly once')
    require((f.grants / 'grants.env').stat().st_mode & 0o777 == 0o600, 'minted env is not mode 0600')
    require((f.grants / 'grants.metadata.json').stat().st_mode & 0o777 == 0o600, 'minted metadata is not mode 0600')
    f.launched()

def case_default_graceful(f, down=False):
    f.env['AGISTACK_DESKTOP_GRANTS_REUSE_ONLY'] = '0'
    f.env.update(f.values())
    if down:
        f.write()
        f.env['STUB_DOCS_EXIT'] = '7'
    else:
        f.env['STUB_BOOTSTRAP_EXIT'] = '1'
    require(f.run().returncode == 0, 'default graceful failure blocked local launch')
    f.launched(local=True)
    require(not list(f.grants.glob('.grants.*.tmp.*')), 'failed bootstrap left temporary output')

def case_make(f, relative=False):
    if relative:
        f.grants = f.agi / 'relative configured grants'
        f.env['AGISTACK_DESKTOP_GRANTS_DIR'] = 'relative configured grants'
        f.env['STUB_ENV_FILE'] = str(f.grants / 'grants.env')
    f.write()
    default = f.agi / '.local/desktop-grants'
    default.mkdir(parents=True)
    marker = f.root / 'default-file-sourced'
    (default / 'grants.env').write_text('touch ' + shlex.quote(str(marker)) + '\n')
    require(f.run(make=True).returncode == 0, 'Make configured-directory launch failed')
    f.launched()
    require(not marker.exists(), 'Make loaded the default grant file')
    require(Path(f.events('launch')[0]['cwd']).resolve() == f.app.resolve(), 'Make launcher cwd changed')

def case_exit(f):
    f.write()
    f.env['STUB_LAUNCH_EXIT'] = '23'
    require(f.run().returncode == 23, 'launcher exit code was not propagated')
    f.launched()

def case_snapshot(f):
    path = f.write()
    f.env['STUB_REWRITE_AFTER_PROBE'] = '1'
    require(f.run().returncode == 0, 'validated snapshot was not retained')
    require(path.read_text() == 'invalid rewritten file\n', 'rewrite fixture did not run')
    f.launched()

def case_make_failure(f):
    f.write()
    f.env['STUB_LAUNCH_EXIT'] = '23'
    require(f.run(make=True).returncode != 0, 'Make swallowed launcher failure')
    f.launched()

def local_only(f, stored=None, make=False, bad_origin=False, launch_exit=0, standalone=False):
    f.env.update(f.values())
    f.env.update(AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY='1',
                 AGISTACK_DESKTOP_GRANTS_REUSE_ONLY='0', STUB_LAUNCH_EXIT=str(launch_exit))
    if stored == 'valid':
        f.write()
    elif stored == 'malformed':
        f.write(extra='this grant file must not be loaded\n')
    if bad_origin:
        f.env['AGISTACK_DESKTOP_GRANTS_API_BASE'] = 'not-an-api-origin'
    path = f.grants / 'grants.env'
    before = path.read_bytes() if path.exists() else None
    result = f.run(make=make, standalone=standalone)
    require(result.returncode == launch_exit, 'local-only launch returned the wrong status')
    require(not f.events('docs') and not f.events('probe') and not f.events('bootstrap'),
            'local-only reached HTTP or bootstrap')
    require((path.read_bytes() if path.exists() else None) == before,
            'local-only changed or created a grant file')
    require(not (f.grants / 'grants.metadata.json').exists(), 'local-only created grant metadata')
    if standalone:
        require(not f.events('launch'), 'standalone local-only launched a command')
    else:
        f.launched(local=True)


def local_only_conflict(f, reuse=False):
    f.write()
    f.env.update(AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY='1',
                 AGISTACK_DESKTOP_GRANTS_REUSE_ONLY='1' if reuse else '0')
    if not reuse:
        f.env['AGISTACK_DESKTOP_GRANTS_FORCE'] = '1'
    f.fail_closed(expect_no_curl=True)


def local_only_invalid_flag(f):
    f.write()
    f.env['AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY'] = 'true'
    f.fail_closed(expect_no_curl=True)


def local_only_disabled(f):
    f.env['AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY'] = '0'
    case_valid(f)


cases = [
    ('local-only-missing-clears-inherited', local_only),
    ('local-only-ignores-valid-file', lambda f: local_only(f, stored='valid')),
    ('local-only-ignores-malformed-file', lambda f: local_only(f, stored='malformed')),
    ('local-only-does-not-require-api-origin', lambda f: local_only(f, bad_origin=True)),
    ('local-only-reuse-conflict', lambda f: local_only_conflict(f, reuse=True)),
    ('local-only-force-conflict', local_only_conflict),
    ('local-only-invalid-flag', local_only_invalid_flag),
    ('local-only-launch-exit', lambda f: local_only(f, launch_exit=23)),
    ('local-only-standalone', lambda f: local_only(f, standalone=True)),
    ('local-only-canonical-make', lambda f: local_only(f, make=True)),
    ('local-only-zero-keeps-reuse', local_only_disabled),
    ('missing', case_missing), ('inherited-not-file', case_inherited),
    ('unknown-field', lambda f: invalid_text(f, 'export UNEXPECTED_FIELD=value\n')),
    ('duplicate-field', lambda f: invalid_text(f, 'export ' + keys[2] + '=true\n')),
    ('arbitrary-shell-command', case_command),
    ('bad-sidecar-credential', lambda f: invalid_values(f, lambda v: v.update({keys[0]:'ms_dp_' + 'G'*64}))),
    ('bad-renderer-credential', lambda f: invalid_values(f, lambda v: v.update({keys[3]:'ms_dp_short'}))),
    ('duplicate-credential-pair', lambda f: invalid_values(f, lambda v: v.update({keys[3]:tokens[0]}))),
    ('missing-sidecar', lambda f: invalid_values(f, lambda v: v.pop(keys[0]))),
    ('wrong-sidecar-origin', lambda f: invalid_values(f, lambda v: v.update({keys[1]:'http://127.0.0.1:18082'}))),
    ('wrong-renderer-origin', lambda f: invalid_values(f, lambda v: v.update({keys[4]:'http://127.0.0.1:18082'}))),
    ('missing-ack', lambda f: invalid_values(f, lambda v: v.pop(keys[2]))),
    ('invalid-ack', lambda f: invalid_values(f, lambda v: v.update({keys[5]:'yes'}))),
    ('force-conflict', case_force), ('docs-unreachable', case_down),
    ('requested-origin-path', lambda f: case_bad_origin(f, origin + '/api')),
    ('requested-origin-userinfo', lambda f: case_bad_origin(f, 'http://name@127.0.0.1:18081')),
    ('requested-remote-http', lambda f: case_bad_origin(f, 'http://example.invalid:18081')),
    ('quoted-ipv6-loopback', case_ipv6),
    ('sidecar-rejected', lambda f: case_rejected(f, 'SIDECAR')),
    ('renderer-rejected', lambda f: case_rejected(f, 'RENDERER')),
    ('curl-nonzero-with-200', lambda f: case_rejected(f, 'RENDERER', '200', '7')),
    ('valid-unquoted-200', case_valid), ('valid-quoted-404-ack-false', lambda f: case_valid(f, True)),
    ('default-mint-missing', case_default_mint),
    ('default-mint-invalid', lambda f: case_default_mint(f, invalid=True)),
    ('default-force-mint', lambda f: case_default_mint(f, force=True)),
    ('default-docs-graceful', lambda f: case_default_graceful(f, down=True)),
    ('default-bootstrap-graceful', case_default_graceful),
    ('make-absolute-spaced-directory', case_make),
    ('make-relative-spaced-directory', lambda f: case_make(f, relative=True)),
    ('launcher-exit-propagation', case_exit), ('make-launcher-failure', case_make_failure),
    ('validated-snapshot-after-rewrite', case_snapshot),
]
failures = 0
print('TAP version 13')
for number, (name, test) in enumerate(cases, 1):
    fixture = Fixture(name)
    try:
        test(fixture)
        print('ok', number, '-', name)
    except Exception as error:
        failures += 1
        print('not ok', number, '-', name)
        # Only constant assertion messages; never print subprocess output or env.
        print('  #', str(error) if isinstance(error, AssertionError) else type(error).__name__)
    finally:
        fixture.close()
print('1..' + str(len(cases)))
print('# tests', len(cases))
print('# pass', len(cases) - failures)
print('# fail', failures)
sys.exit(bool(failures))
PY
