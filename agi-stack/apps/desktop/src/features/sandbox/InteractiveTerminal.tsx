import { useEffect, useRef } from 'react';

import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

import { isSafeTerminalLink } from './terminalLinkPolicy';
import './InteractiveTerminal.css';

type InteractiveTerminalProps = {
  ariaLabel: string;
  connected: boolean;
  outputChunks: readonly string[];
  onInput: (data: string) => void;
  onResize: (cols: number, rows: number) => void;
};

export function InteractiveTerminal({
  ariaLabel,
  connected,
  outputChunks,
  onInput,
  onResize,
}: InteractiveTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const outputRef = useRef('');
  const connectedRef = useRef(connected);
  const inputRef = useRef(onInput);
  const resizeRef = useRef(onResize);

  useEffect(() => {
    connectedRef.current = connected;
    inputRef.current = onInput;
    resizeRef.current = onResize;
  }, [connected, onInput, onResize]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const terminal = new Terminal({
      convertEol: false,
      cursorBlink: true,
      cursorStyle: 'block',
      fontFamily: 'Menlo, Monaco, Consolas, "Liberation Mono", monospace',
      fontSize: 13,
      scrollback: 5_000,
      theme: {
        background: '#0b1018',
        foreground: '#d6e2f0',
        cursor: '#62d7ff',
        selectionBackground: '#23445f',
      },
    });
    const fit = new FitAddon();
    const webLinks = new WebLinksAddon((_event, uri) => {
      if (!isSafeTerminalLink(uri)) return;
      window.open(uri, '_blank', 'noopener,noreferrer');
    });
    terminal.loadAddon(fit);
    terminal.loadAddon(webLinks);
    terminal.open(container);
    terminalRef.current = terminal;

    const inputSubscription = terminal.onData((data) => {
      if (connectedRef.current) inputRef.current(data);
    });
    let lastSize = '';
    let frame: number | null = null;
    const fitAndNotify = () => {
      frame = null;
      if (!container.isConnected) return;
      fit.fit();
      const size = `${terminal.cols}x${terminal.rows}`;
      if (size === lastSize) return;
      lastSize = size;
      resizeRef.current(terminal.cols, terminal.rows);
    };
    // Fitting changes xterm's layout. Defer it beyond ResizeObserver delivery and
    // merge notifications from the same frame instead of synchronously resizing.
    const scheduleFit = () => {
      if (frame === null) frame = requestAnimationFrame(fitAndNotify);
    };
    const resizeObserver = new ResizeObserver(scheduleFit);
    resizeObserver.observe(container);
    scheduleFit();

    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      inputSubscription.dispose();
      terminal.dispose();
      terminalRef.current = null;
      outputRef.current = '';
    };
  }, []);

  const output = outputChunks.join('');
  useEffect(() => {
    const terminal = terminalRef.current;
    if (!terminal || output === outputRef.current) return;
    if (output.startsWith(outputRef.current)) {
      terminal.write(output.slice(outputRef.current.length));
    } else {
      terminal.reset();
      terminal.write(output);
    }
    outputRef.current = output;
  }, [output]);

  return (
    <div
      className="desktop-interactive-terminal"
      role="application"
      aria-label={ariaLabel}
      data-connected={connected}
    >
      <div ref={containerRef} className="desktop-interactive-terminal-host" />
    </div>
  );
}
