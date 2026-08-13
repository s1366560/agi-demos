export type MCPCommandParseResult =
  | { ok: true; argv: string[] }
  | {
      ok: false;
      reason: 'empty' | 'unterminated_quote' | 'trailing_escape' | 'executable_not_absolute';
    };

export function parseMCPStdioCommand(value: string): MCPCommandParseResult {
  const argv: string[] = [];
  let current = '';
  let quote: 'single' | 'double' | null = null;
  let escaped = false;
  let tokenStarted = false;

  for (const character of value) {
    if (escaped) {
      current += character;
      tokenStarted = true;
      escaped = false;
      continue;
    }
    if (character === '\\' && quote !== 'single') {
      escaped = true;
      tokenStarted = true;
      continue;
    }
    if (character === "'" && quote !== 'double') {
      quote = quote === 'single' ? null : 'single';
      tokenStarted = true;
      continue;
    }
    if (character === '"' && quote !== 'single') {
      quote = quote === 'double' ? null : 'double';
      tokenStarted = true;
      continue;
    }
    if (/\s/u.test(character) && quote === null) {
      if (tokenStarted) {
        argv.push(current);
        current = '';
        tokenStarted = false;
      }
      continue;
    }
    current += character;
    tokenStarted = true;
  }

  if (escaped) return { ok: false, reason: 'trailing_escape' };
  if (quote !== null) return { ok: false, reason: 'unterminated_quote' };
  if (tokenStarted) argv.push(current);
  if (argv.length === 0) return { ok: false, reason: 'empty' };
  if (!argv[0].startsWith('/')) return { ok: false, reason: 'executable_not_absolute' };
  return { ok: true, argv };
}
