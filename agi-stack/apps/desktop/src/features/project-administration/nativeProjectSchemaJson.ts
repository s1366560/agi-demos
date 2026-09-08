import { schemaAssert } from './nativeProjectSchemaShape';

/** Reject duplicate keys and noninteger protocol tokens before any shape decoder sees a value. */
export function parseNativeProjectSchemaJson(text: string): unknown {
  let position = 0;
  const white = () => {
    while (position < text.length && /[ \t\r\n]/.test(text[position]!)) position++;
  };
  const string = (): string => {
    schemaAssert(text[position] === '"');
    const start = position++;
    while (position < text.length) {
      const character = text[position++];
      if (character === '\\') position++;
      else if (character === '"') return JSON.parse(text.slice(start, position)) as string;
    }
    return schemaAssert(false) as never;
  };
  const opaque = (path: readonly (string | number)[]): boolean =>
    path.some(
      (part, index) =>
        part === 'schema' &&
        index >= 3 &&
        typeof path[index - 1] === 'number' &&
        (path[index - 2] === 'entity_types' || path[index - 2] === 'edge_types') &&
        path[index - 3] === 'document',
    );
  const value = (path: readonly (string | number)[]): unknown => {
    schemaAssert(path.length <= 30);
    white();
    if (text[position] === '"') return string();
    if (text[position] === '{') {
      position++;
      white();
      const entries: [string, unknown][] = [],
        seen = new Set<string>();
      if (text[position] === '}') {
        position++;
        return {};
      }
      while (true) {
        white();
        const key = string();
        schemaAssert(!seen.has(key));
        seen.add(key);
        white();
        schemaAssert(text[position++] === ':');
        entries.push([key, value([...path, key])]);
        white();
        const separator = text[position++];
        if (separator === '}') return Object.fromEntries(entries);
        schemaAssert(separator === ',');
      }
    }
    if (text[position] === '[') {
      position++;
      white();
      const items: unknown[] = [];
      if (text[position] === ']') {
        position++;
        return items;
      }
      while (true) {
        items.push(value([...path, items.length]));
        white();
        const separator = text[position++];
        if (separator === ']') return items;
        schemaAssert(separator === ',');
      }
    }
    for (const [literal, result] of [
      ['null', null],
      ['true', true],
      ['false', false],
    ] as const) {
      if (text.startsWith(literal, position)) {
        position += literal.length;
        return result;
      }
    }
    const token = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(position))?.[0];
    schemaAssert(token);
    position += token.length;
    schemaAssert(opaque(path) || (token !== '-0' && !/[.eE]/.test(token)));
    const number = Number(token);
    schemaAssert(Number.isFinite(number) && Math.abs(number) <= Number.MAX_SAFE_INTEGER);
    return number;
  };
  const result = value([]);
  white();
  schemaAssert(position === text.length);
  return result;
}
