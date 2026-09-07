/**
 * TerminalImpl - Actual terminal implementation with xterm.js
 *
 * This file is dynamically imported to defer loading xterm.js
 * until the terminal is actually needed.
 */

import { useEffect, useLayoutEffect, useRef, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { Terminal } from '@xterm/xterm';

import { useThemeColors } from '../../../hooks/useThemeColor';
import {
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '../../../plugins/webOperationAdmissionV2';
import { TerminalRetainedSessionV2 } from '../../../services/terminalRetainedSessionV2';

interface TerminalImplProps {
  sandboxId: string;
  projectId?: string | undefined;
  sessionId?: string | undefined;
  onConnect: (sessionId: string) => void;
  onDisconnect: () => void;
  onError: (error: string) => void;
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  isFullscreen: boolean;
}

// Token map for terminal theme colors (resolved reactively via useThemeColors)
const TERMINAL_TOKEN_MAP = {
  background: '--color-background-dark',
  foreground: '--color-text-inverse',
  cursor: '--color-primary',
  cursorAccent: '--color-background-dark',
  selectionBackground: '--color-primary-light',
  black: '--color-background-dark',
  red: '--color-error',
  green: '--color-success',
  yellow: '--color-warning',
  blue: '--color-info',
  magenta: '--color-tile-purple',
  cyan: '--color-tile-cyan',
  white: '--color-text-inverse',
  brightBlack: '--color-text-muted',
  brightRed: '--color-error-light',
  brightGreen: '--color-success-light',
  brightYellow: '--color-warning-light',
  brightBlue: '--color-info-light',
  brightMagenta: '--color-tile-pink',
  brightCyan: '--color-tile-cyan',
  brightWhite: '--color-text-inverse',
} as const;

// Fallback hex values (original palette) for tokens that may not resolve
const TERMINAL_FALLBACKS: Record<string, string> = {
  background: '#141416',
  foreground: '#e8eaed',
  cursor: '#ededed',
  cursorAccent: '#141416',
  selectionBackground: '#404040',
  black: '#141416',
  red: '#ef4444',
  green: '#10b981',
  yellow: '#f59e0b',
  blue: '#3b82f6',
  magenta: '#8b5cf6',
  cyan: '#06b6d4',
  white: '#e8eaed',
  brightBlack: '#7d8599',
  brightRed: '#fee2e2',
  brightGreen: '#d1fae5',
  brightYellow: '#fef3c7',
  brightBlue: '#dbeafe',
  brightMagenta: '#ec4899',
  brightCyan: '#06b6d4',
  brightWhite: '#e8eaed',
};

export function TerminalImpl({
  sandboxId,
  projectId,
  sessionId,
  onConnect,
  onDisconnect,
  onError,
  isFullscreen,
}: TerminalImplProps) {
  const { t } = useTranslation();
  const terminalRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<{
    terminal: Terminal;
    fit: FitAddon;
    session: TerminalRetainedSessionV2;
    operation: WebOperationContextV2;
  } | null>(null);
  const resolvedColors = useThemeColors(TERMINAL_TOKEN_MAP);
  const terminalTheme = useMemo(() => {
    const theme: Record<string, string> = {};
    for (const key of Object.keys(TERMINAL_TOKEN_MAP) as Array<keyof typeof TERMINAL_TOKEN_MAP>)
      theme[key] = resolvedColors[key] || TERMINAL_FALLBACKS[key] || '';
    return theme;
  }, [resolvedColors]);
  const themeRef = useRef(terminalTheme);
  useLayoutEffect(() => {
    themeRef.current = terminalTheme;
  }, [terminalTheme]);
  // Server-issued session IDs and parent callbacks may change after connection. They must
  // not replace an already-admitted UI lifetime or redirect its callbacks to a new owner.
  const callbacks = useRef({ onConnect, onDisconnect, onError, t, sessionId });
  useLayoutEffect(() => {
    callbacks.current = { onConnect, onDisconnect, onError, t, sessionId };
  });
  useLayoutEffect(() => {
    const target = terminalRef.current;
    if (!target) return;
    let active = true;
    const isActive = () => active;
    const captured = callbacks.current;
    let terminal: Terminal | undefined;
    const session = new TerminalRetainedSessionV2({
      sandboxId,
      ...(projectId ? { projectId } : {}),
      ...(captured.sessionId ? { sessionId: captured.sessionId } : {}),
      onAdmitted(operation) {
        operation.check();
        if (!active) throw new DOMException('Terminal unmounted', 'AbortError');
        terminal = new Terminal({
          cursorBlink: true,
          fontSize: 14,
          fontFamily: 'Menlo, Monaco, "Courier New", monospace',
          theme: themeRef.current,
          allowProposedApi: true,
        });
        const ownTerminal = terminal;
        let input: { dispose(): void } | undefined;
        let observer: ResizeObserver | undefined;
        const cleanup = () => {
          active = false;
          const failures: unknown[] = [];
          for (const dispose of [
            () => observer?.disconnect(),
            () => input?.dispose(),
            () => {
              ownTerminal.dispose();
            },
          ]) {
            try {
              dispose();
            } catch (error) {
              failures.push(error);
            }
          }
          if (viewRef.current?.session === session) viewRef.current = null;
          if (failures.length)
            throw new WebOperationCleanupErrorV2(failures, 'Terminal UI cleanup failed');
        };
        try {
          const fit = new FitAddon();
          ownTerminal.loadAddon(fit);
          ownTerminal.loadAddon(new WebLinksAddon());
          ownTerminal.open(target);
          fit.fit();
          viewRef.current = { terminal: ownTerminal, fit, session, operation };
          input = ownTerminal.onData((data) => {
            if (!active) return;
            try {
              operation.check();
            } catch {
              return;
            }
            session.sendInput(data);
          });
          observer = new ResizeObserver(() => {
            if (!active) return;
            try {
              operation.check();
            } catch {
              return;
            }
            fit.fit();
            session.resize(ownTerminal.cols, ownTerminal.rows);
          });
          observer.observe(target);
          return cleanup;
        } catch (error) {
          cleanup();
          throw error;
        }
      },
      onConnect(id) {
        if (!active) return;
        const operation = session.getOperationContext();
        if (!operation) return;
        operation.check();
        captured.onConnect(id);
        // A parent callback can synchronously retire this owner.
        if (!isActive()) return;
        operation.check();
        const view = viewRef.current;
        if (!view || view.session !== session || view.operation !== operation) return;
        view.fit.fit();
        operation.check();
        session.resize(view.terminal.cols, view.terminal.rows);
        terminal?.writeln(
          `\x1b[32m${captured.t('components.sandboxTerminal.connectedWelcome', { defaultValue: 'Connected to sandbox terminal' })}\x1b[0m`
        );
        terminal?.writeln('');
      },
      onOutput(data) {
        if (active) terminal?.write(data);
      },
      onDisconnect() {
        if (active) captured.onDisconnect();
      },
      onError(error) {
        if (active) captured.onError(error.message);
      },
    });
    void session.connect().catch((error: unknown) => {
      if (active && !(error instanceof DOMException && error.name === 'AbortError'))
        captured.onError(
          captured.t('components.sandboxTerminal.connectionError', {
            defaultValue: 'Connection error',
          })
        );
    });
    return () => {
      active = false;
      void session.disconnect().catch(() => {
        console.warn('Terminal cleanup failed');
      });
    };
  }, [sandboxId, projectId]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const timer = setTimeout(() => {
      if (viewRef.current !== view) return;
      try {
        view.operation.check();
      } catch {
        return;
      }
      view.fit.fit();
      view.session.resize(view.terminal.cols, view.terminal.rows);
    }, 100);
    const cancel = () => {
      clearTimeout(timer);
    };
    view.operation.signal.addEventListener('abort', cancel, { once: true });
    return () => {
      cancel();
      view.operation.signal.removeEventListener('abort', cancel);
    };
  }, [isFullscreen]);
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    try {
      view.operation.check();
    } catch {
      return;
    }
    view.terminal.options.theme = terminalTheme;
  }, [terminalTheme]);
  return <div ref={terminalRef} className="h-full w-full" style={{ padding: '4px' }} />;
}
export default TerminalImpl;
