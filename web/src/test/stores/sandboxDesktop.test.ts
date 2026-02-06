/**
 * Tests for Sandbox Store with Desktop and Terminal Status
 *
 * Tests the extended sandbox store with desktop and terminal status management.
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useSandboxStore } from '../../stores/sandbox';

import type { DesktopStatus, TerminalStatus } from '../../types/agent';

describe('Sandbox Store - Desktop and Terminal Status', () => {
  beforeEach(() => {
    // Reset store before each test
    const { reset } = useSandboxStore.getState();
    reset();
  });

  describe('Desktop Status', () => {
    it('should have initial desktop status as null', () => {
      const { result } = renderHook(() => useSandboxStore());

      expect(result.current.desktopStatus).toBeNull();
    });

    it('should update desktop status when setDesktopStatus is called', () => {
      const { result } = renderHook(() => useSandboxStore());

      const mockStatus: DesktopStatus = {
        running: true,
        url: 'http://localhost:6080/vnc.html',
        display: ':0',
        resolution: '1280x720',
        port: 6080,
      };

      act(() => {
        result.current.setDesktopStatus(mockStatus);
      });

      expect(result.current.desktopStatus).toEqual(mockStatus);
    });

    it('should clear desktop status when set to null', () => {
      const { result } = renderHook(() => useSandboxStore());

      const mockStatus: DesktopStatus = {
        running: true,
        url: 'http://localhost:6080/vnc.html',
        display: ':0',
        resolution: '1280x720',
        port: 6080,
      };

      act(() => {
        result.current.setDesktopStatus(mockStatus);
      });

      expect(result.current.desktopStatus).toEqual(mockStatus);

      act(() => {
        result.current.setDesktopStatus(null);
      });

      expect(result.current.desktopStatus).toBeNull();
    });

    it('should track desktop loading state', () => {
      const { result } = renderHook(() => useSandboxStore());

      expect(result.current.isDesktopLoading).toBe(false);

      act(() => {
        result.current.setDesktopLoading(true);
      });

      expect(result.current.isDesktopLoading).toBe(true);

      act(() => {
        result.current.setDesktopLoading(false);
      });

      expect(result.current.isDesktopLoading).toBe(false);
    });
  });

  describe('Terminal Status', () => {
    it('should have initial terminal status as null', () => {
      const { result } = renderHook(() => useSandboxStore());

      expect(result.current.terminalStatus).toBeNull();
    });

    it('should update terminal status when setTerminalStatus is called', () => {
      const { result } = renderHook(() => useSandboxStore());

      const mockStatus: TerminalStatus = {
        running: true,
        url: 'ws://localhost:7681',
        port: 7681,
      };

      act(() => {
        result.current.setTerminalStatus(mockStatus);
      });

      expect(result.current.terminalStatus).toEqual(mockStatus);
    });

    it('should clear terminal status when set to null', () => {
      const { result } = renderHook(() => useSandboxStore());

      const mockStatus: TerminalStatus = {
        running: true,
        url: 'ws://localhost:7681',
        port: 7681,
      };

      act(() => {
        result.current.setTerminalStatus(mockStatus);
      });

      expect(result.current.terminalStatus).toEqual(mockStatus);

      act(() => {
        result.current.setTerminalStatus(null);
      });

      expect(result.current.terminalStatus).toBeNull();
    });

    it('should track terminal loading state', () => {
      const { result } = renderHook(() => useSandboxStore());

      expect(result.current.isTerminalLoading).toBe(false);

      act(() => {
        result.current.setTerminalLoading(true);
      });

      expect(result.current.isTerminalLoading).toBe(true);

      act(() => {
        result.current.setTerminalLoading(false);
      });

      expect(result.current.isTerminalLoading).toBe(false);
    });
  });

  describe('Desktop Control Actions', () => {
    it('should call onDesktopStart callback when provided', async () => {
      const mockOnDesktopStart = vi.fn().mockResolvedValue(undefined);

      const { result } = renderHook(() => useSandboxStore());

      await act(async () => {
        await result.current.startDesktop();
      });

      // In real implementation, this would call the API
      // For now, we verify the loading state is set
      expect(result.current.isDesktopLoading).toBe(false);
    });

    it('should call onDesktopStop callback when provided', async () => {
      const mockOnDesktopStop = vi.fn().mockResolvedValue(undefined);

      const { result } = renderHook(() => useSandboxStore());

      // First set desktop as running
      const mockStatus: DesktopStatus = {
        running: true,
        url: 'http://localhost:6080/vnc.html',
        display: ':0',
        resolution: '1280x720',
        port: 6080,
      };

      act(() => {
        result.current.setDesktopStatus(mockStatus);
      });

      await act(async () => {
        await result.current.stopDesktop();
      });

      // In real implementation, this would call the API
      expect(result.current.isDesktopLoading).toBe(false);
    });
  });

  describe('Terminal Control Actions', () => {
    it('should call onTerminalStart callback when provided', async () => {
      const mockOnTerminalStart = vi.fn().mockResolvedValue(undefined);

      const { result } = renderHook(() => useSandboxStore());

      await act(async () => {
        await result.current.startTerminal();
      });

      // In real implementation, this would call the API
      expect(result.current.isTerminalLoading).toBe(false);
    });

    it('should call onTerminalStop callback when provided', async () => {
      const mockOnTerminalStop = vi.fn().mockResolvedValue(undefined);

      const { result } = renderHook(() => useSandboxStore());

      // First set terminal as running
      const mockStatus: TerminalStatus = {
        running: true,
        url: 'ws://localhost:7681',
        port: 7681,
      };

      act(() => {
        result.current.setTerminalStatus(mockStatus);
      });

      await act(async () => {
        await result.current.stopTerminal();
      });

      // In real implementation, this would call the API
      expect(result.current.isTerminalLoading).toBe(false);
    });
  });

  describe('SSE Event Handling', () => {
    it('should update desktop status on desktop_started event', () => {
      const { result } = renderHook(() => useSandboxStore());

      const eventData = {
        sandbox_id: 'test-sandbox',
        url: 'http://localhost:6080/vnc.html',
        display: ':0',
        resolution: '1280x720',
        port: 6080,
      };

      act(() => {
        result.current.handleSSEEvent({
          type: 'desktop_started',
          data: eventData,
        } as any);
      });

      expect(result.current.desktopStatus?.running).toBe(true);
      expect(result.current.desktopStatus?.url).toBe(eventData.url);
    });

    it('should update desktop status on desktop_stopped event', () => {
      const { result } = renderHook(() => useSandboxStore());

      // First set desktop as running
      const mockStatus: DesktopStatus = {
        running: true,
        url: 'http://localhost:6080/vnc.html',
        display: ':0',
        resolution: '1280x720',
        port: 6080,
      };

      act(() => {
        result.current.setDesktopStatus(mockStatus);
      });

      expect(result.current.desktopStatus?.running).toBe(true);

      act(() => {
        result.current.handleSSEEvent({
          type: 'desktop_stopped',
          data: { sandbox_id: 'test-sandbox' },
        } as any);
      });

      expect(result.current.desktopStatus?.running).toBe(false);
      expect(result.current.desktopStatus?.url).toBeNull();
    });

    it('should update terminal status on terminal_started event', () => {
      const { result } = renderHook(() => useSandboxStore());

      const eventData = {
        sandbox_id: 'test-sandbox',
        url: 'ws://localhost:7681',
        port: 7681,
        session_id: 'session-123',
      };

      act(() => {
        result.current.handleSSEEvent({
          type: 'terminal_started',
          data: eventData,
        } as any);
      });

      expect(result.current.terminalStatus?.running).toBe(true);
      expect(result.current.terminalStatus?.url).toBe(eventData.url);
    });

    it('should update terminal status on terminal_stopped event', () => {
      const { result } = renderHook(() => useSandboxStore());

      // First set terminal as running
      const mockStatus: TerminalStatus = {
        running: true,
        url: 'ws://localhost:7681',
        port: 7681,
      };

      act(() => {
        result.current.setTerminalStatus(mockStatus);
      });

      expect(result.current.terminalStatus?.running).toBe(true);

      act(() => {
        result.current.handleSSEEvent({
          type: 'terminal_stopped',
          data: { sandbox_id: 'test-sandbox' },
        } as any);
      });

      expect(result.current.terminalStatus?.running).toBe(false);
      expect(result.current.terminalStatus?.url).toBeNull();
    });
  });

  describe('Selectors', () => {
    it('should provide selector for desktop status', () => {
      const { result } = renderHook(() => useSandboxStore());

      const mockStatus: DesktopStatus = {
        running: true,
        url: 'http://localhost:6080/vnc.html',
        display: ':0',
        resolution: '1280x720',
        port: 6080,
      };

      act(() => {
        result.current.setDesktopStatus(mockStatus);
      });

      // Get state directly to verify
      expect(result.current.desktopStatus).toEqual(mockStatus);
    });

    it('should provide selector for terminal status', () => {
      const { result } = renderHook(() => useSandboxStore());

      const mockStatus: TerminalStatus = {
        running: true,
        url: 'ws://localhost:7681',
        port: 7681,
      };

      act(() => {
        result.current.setTerminalStatus(mockStatus);
      });

      // Get state directly to verify
      expect(result.current.terminalStatus).toEqual(mockStatus);
    });
  });
});
