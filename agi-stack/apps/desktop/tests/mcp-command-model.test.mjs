import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { formatMCPStdioCommand, mcpStdioCommandArgv, parseMCPStdioCommand } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/mcpCommandModel.js',
);

test('MCP stdio commands are normalized to absolute direct argv without a shell', () => {
  assert.deepEqual(parseMCPStdioCommand('/opt/homebrew/bin/node /opt/homebrew/bin/gitnexus mcp'), {
    ok: true,
    argv: ['/opt/homebrew/bin/node', '/opt/homebrew/bin/gitnexus', 'mcp'],
  });
  assert.deepEqual(parseMCPStdioCommand('/usr/bin/python -m "example server" --flag=\\ value'), {
    ok: true,
    argv: ['/usr/bin/python', '-m', 'example server', '--flag= value'],
  });
  assert.deepEqual(parseMCPStdioCommand("/usr/bin/tool '' 'literal value'"), {
    ok: true,
    argv: ['/usr/bin/tool', '', 'literal value'],
  });
});

test('MCP stdio command parsing rejects incomplete structural input', () => {
  assert.deepEqual(parseMCPStdioCommand('   '), { ok: false, reason: 'empty' });
  assert.deepEqual(parseMCPStdioCommand('node "missing'), {
    ok: false,
    reason: 'unterminated_quote',
  });
  assert.deepEqual(parseMCPStdioCommand('node trailing\\'), {
    ok: false,
    reason: 'trailing_escape',
  });
  assert.deepEqual(parseMCPStdioCommand('node /opt/homebrew/bin/gitnexus mcp'), {
    ok: false,
    reason: 'executable_not_absolute',
  });
});

test('MCP stdio command formatting preserves complete command and args argv', () => {
  const argv = mcpStdioCommandArgv(
    ['/usr/bin/python3', '-m'],
    ['example server', '', 'quote"value', "single'value", 'back\\slash'],
  );
  assert.deepEqual(argv, [
    '/usr/bin/python3',
    '-m',
    'example server',
    '',
    'quote"value',
    "single'value",
    'back\\slash',
  ]);
  assert.deepEqual(parseMCPStdioCommand(formatMCPStdioCommand(argv)), { ok: true, argv });
  assert.deepEqual(mcpStdioCommandArgv('/usr/bin/node', ['server.js', '--stdio']), [
    '/usr/bin/node',
    'server.js',
    '--stdio',
  ]);
});
