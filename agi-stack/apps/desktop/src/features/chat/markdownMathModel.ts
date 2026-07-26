function isEscapedAt(content: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && content[cursor] === '\\'; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}

function isWhitespace(character: string | undefined): boolean {
  return character !== undefined && /\s/u.test(character);
}

type FenceMarker = {
  character: '`' | '~';
  length: number;
  remainder: string;
};

function readFenceMarker(line: string): FenceMarker | null {
  let cursor = 0;
  while (cursor < line.length && cursor < 4 && line[cursor] === ' ') cursor += 1;
  const character = line[cursor];
  if ((character !== '`' && character !== '~') || cursor > 3) return null;
  let end = cursor;
  while (line[end] === character) end += 1;
  const length = end - cursor;
  if (length < 3) return null;
  return { character, length, remainder: line.slice(end) };
}

function maskInlineCode(line: string): string {
  let masked = '';
  for (let cursor = 0; cursor < line.length; cursor += 1) {
    if (line[cursor] !== '`') {
      masked += line[cursor];
      continue;
    }
    let openerEnd = cursor;
    while (line[openerEnd] === '`') openerEnd += 1;
    const delimiterLength = openerEnd - cursor;
    let closingStart = -1;
    for (let candidate = openerEnd; candidate < line.length; candidate += 1) {
      if (line[candidate] !== '`') continue;
      let closingEnd = candidate;
      while (line[closingEnd] === '`') closingEnd += 1;
      if (closingEnd - candidate === delimiterLength) {
        closingStart = candidate;
        break;
      }
      candidate = closingEnd - 1;
    }
    if (closingStart < 0) {
      masked += line.slice(cursor, openerEnd);
      cursor = openerEnd - 1;
      continue;
    }
    const closingEnd = closingStart + delimiterLength;
    masked += ' '.repeat(closingEnd - cursor);
    cursor = closingEnd - 1;
  }
  return masked;
}

function contentOutsideMarkdownCode(content: string): string {
  let fence: Pick<FenceMarker, 'character' | 'length'> | null = null;
  return content
    .split('\n')
    .map((line) => {
      const marker = readFenceMarker(line);
      if (fence) {
        if (
          marker?.character === fence.character &&
          marker.length >= fence.length &&
          marker.remainder.trim() === ''
        ) {
          fence = null;
        }
        return '';
      }
      if (marker) {
        fence = marker;
        return '';
      }
      if (line.startsWith('    ') || line.startsWith('\t')) return '';
      return maskInlineCode(line);
    })
    .join('\n');
}

function hasDisplayMath(content: string): boolean {
  for (let start = 0; start < content.length - 1; start += 1) {
    if (
      content[start] !== '$' ||
      content[start + 1] !== '$' ||
      isEscapedAt(content, start)
    ) {
      continue;
    }
    for (let end = start + 2; end < content.length - 1; end += 1) {
      if (
        content[end] === '$' &&
        content[end + 1] === '$' &&
        !isEscapedAt(content, end)
      ) {
        if (content.slice(start + 2, end).trim()) return true;
        start = end + 1;
        break;
      }
    }
  }
  return false;
}

function hasInlineMath(content: string): boolean {
  for (let start = 0; start < content.length; start += 1) {
    if (
      content[start] !== '$' ||
      content[start - 1] === '$' ||
      content[start + 1] === '$' ||
      isEscapedAt(content, start) ||
      isWhitespace(content[start + 1])
    ) {
      continue;
    }
    for (let end = start + 1; end < content.length; end += 1) {
      if (content[end] === '\n') break;
      if (
        content[end] === '$' &&
        content[end - 1] !== '$' &&
        content[end + 1] !== '$' &&
        !isEscapedAt(content, end)
      ) {
        if (!isWhitespace(content[end - 1])) return true;
        start = end;
        break;
      }
    }
  }
  return false;
}

/** Detect only the structural delimiters understood by standard Markdown math. */
export function hasMarkdownMathSyntax(content: string): boolean {
  const prose = contentOutsideMarkdownCode(content);
  return hasDisplayMath(prose) || hasInlineMath(prose);
}
