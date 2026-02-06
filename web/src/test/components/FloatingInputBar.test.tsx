/**
 * Tests for FloatingInputBar - Floating input bar for agent messages
 *
 * TDD: Refactor boolean props to use configuration object pattern
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import {
  FloatingInputBar,
  type FloatingInputBarConfig,
} from '../../components/agent/chat/FloatingInputBar';

describe('FloatingInputBar', () => {
  describe('basic functionality', () => {
    it('renders input field with default placeholder', () => {
      render(<FloatingInputBar />);
      expect(screen.getByPlaceholderText(/message the agent/i)).toBeInTheDocument();
    });

    it('renders controlled input with value', () => {
      render(<FloatingInputBar value="Hello" />);
      expect(screen.getByDisplayValue('Hello')).toBeInTheDocument();
    });

    it('calls onChange when input changes', () => {
      const onChange = vi.fn();
      render(<FloatingInputBar onChange={onChange} />);

      const input = screen.getByPlaceholderText(/message the agent/i) as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'Hello' } });

      expect(onChange).toHaveBeenCalledWith('Hello');
    });

    it('calls onSend when send button is clicked', () => {
      const onSend = vi.fn();
      render(<FloatingInputBar value="Hello" onSend={onSend} />);

      const sendButton = screen.getByTitle('Send message');
      fireEvent.click(sendButton);

      expect(onSend).toHaveBeenCalledWith('Hello');
    });

    it('clears input after send when controlled', () => {
      const onSend = vi.fn();
      const onChange = vi.fn();
      render(<FloatingInputBar value="Hello" onChange={onChange} onSend={onSend} />);

      const sendButton = screen.getByTitle('Send message');
      fireEvent.click(sendButton);

      expect(onSend).toHaveBeenCalledWith('Hello');
      // onChange should be called with empty string after send
      expect(onChange).toHaveBeenCalledWith('');
    });

    it('calls onStop when stop button is clicked in disabled state', () => {
      const onStop = vi.fn();
      render(<FloatingInputBar disabled onStop={onStop} />);

      const stopButton = screen.getByTitle(/stop/i);
      fireEvent.click(stopButton);

      expect(onStop).toHaveBeenCalled();
    });

    it('disables input when disabled prop is true', () => {
      render(<FloatingInputBar disabled />);

      const input = screen.getByPlaceholderText(/agent is thinking/i);
      expect(input).toBeDisabled();
    });
  });

  describe('config object pattern', () => {
    it('renders with default config when not provided', () => {
      render(<FloatingInputBar />);
      expect(screen.getByTitle('Attach context')).toBeInTheDocument();
      expect(screen.getByTitle('Voice input')).toBeInTheDocument();
    });

    it('hides attachment button when config.showAttachment is false', () => {
      const config: FloatingInputBarConfig = {
        showAttachment: false,
      };
      render(<FloatingInputBar config={config} />);
      expect(screen.queryByTitle('Attach context')).not.toBeInTheDocument();
    });

    it('hides voice button when config.showVoice is false', () => {
      const config: FloatingInputBarConfig = {
        showVoice: false,
      };
      render(<FloatingInputBar config={config} />);
      expect(screen.queryByTitle('Voice input')).not.toBeInTheDocument();
    });

    it('hides footer when config.showFooter is false', () => {
      const config: FloatingInputBarConfig = {
        showFooter: false,
      };
      render(<FloatingInputBar config={config} />);
      expect(screen.queryByText(/deep search/i)).not.toBeInTheDocument();
    });

    it('shows plan mode button when config.planMode is provided', () => {
      const config: FloatingInputBarConfig = {
        planMode: {
          onPlanMode: vi.fn(),
          isInPlanMode: false,
          disabled: false,
        },
      };
      render(<FloatingInputBar config={config} />);
      expect(screen.getByText(/plan mode/i)).toBeInTheDocument();
    });

    it('shows plan mode active indicator when config.planMode.isInPlanMode is true', () => {
      const config: FloatingInputBarConfig = {
        planMode: {
          onPlanMode: vi.fn(),
          isInPlanMode: true,
          disabled: false,
        },
      };
      render(<FloatingInputBar config={config} />);
      expect(screen.getByText(/in plan mode/i)).toBeInTheDocument();
    });

    it('disables plan mode button when config.planMode.disabled is true', () => {
      const config: FloatingInputBarConfig = {
        planMode: {
          onPlanMode: vi.fn(),
          isInPlanMode: false,
          disabled: true,
        },
      };
      render(<FloatingInputBar config={config} />);
      const planModeButton = screen.getByText(/plan mode/i).closest('button');
      expect(planModeButton).toBeDisabled();
    });

    it('calls onPlanMode when plan mode button is clicked', () => {
      const onPlanMode = vi.fn();
      const config: FloatingInputBarConfig = {
        planMode: {
          onPlanMode,
          isInPlanMode: false,
          disabled: false,
        },
      };
      render(<FloatingInputBar config={config} />);

      const planModeButton = screen.getByText(/plan mode/i).closest('button');
      fireEvent.click(planModeButton!);

      expect(onPlanMode).toHaveBeenCalled();
    });
  });

  describe('backward compatibility with individual props', () => {
    it('respects showAttachment prop when config not provided', () => {
      render(<FloatingInputBar showAttachment={false} />);
      expect(screen.queryByTitle('Attach context')).not.toBeInTheDocument();
    });

    it('respects showVoice prop when config not provided', () => {
      render(<FloatingInputBar showVoice={false} />);
      expect(screen.queryByTitle('Voice input')).not.toBeInTheDocument();
    });

    it('respects showFooter prop when config not provided', () => {
      render(<FloatingInputBar showFooter={false} />);
      expect(screen.queryByText(/deep search/i)).not.toBeInTheDocument();
    });

    it('respects onPlanMode prop when config not provided', () => {
      render(<FloatingInputBar onPlanMode={vi.fn()} />);
      expect(screen.getByText(/plan mode/i)).toBeInTheDocument();
    });

    it('respects isInPlanMode prop when config not provided', () => {
      render(<FloatingInputBar onPlanMode={vi.fn()} isInPlanMode={true} />);
      expect(screen.getByText(/in plan mode/i)).toBeInTheDocument();
    });

    it('respects planModeDisabled prop when config not provided', () => {
      render(<FloatingInputBar onPlanMode={vi.fn()} planModeDisabled={true} />);
      const planModeButton = screen.getByText(/plan mode/i).closest('button');
      expect(planModeButton).toBeDisabled();
    });
  });

  describe('config takes precedence over individual props', () => {
    it('config.showAttachment overrides showAttachment prop', () => {
      const config: FloatingInputBarConfig = {
        showAttachment: true,
      };
      render(<FloatingInputBar showAttachment={false} config={config} />);
      expect(screen.getByTitle('Attach context')).toBeInTheDocument();
    });

    it('config.showVoice overrides showVoice prop', () => {
      const config: FloatingInputBarConfig = {
        showVoice: true,
      };
      render(<FloatingInputBar showVoice={false} config={config} />);
      expect(screen.getByTitle('Voice input')).toBeInTheDocument();
    });
  });

  describe('keyboard interaction', () => {
    it('sends message on Enter key press', () => {
      const onSend = vi.fn();
      render(<FloatingInputBar value="Hello" onChange={vi.fn()} onSend={onSend} />);

      const input = screen.getByPlaceholderText(/message the agent/i);
      fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', charCode: 13 });

      expect(onSend).toHaveBeenCalledWith('Hello');
    });

    it('does not send on Shift+Enter', () => {
      const onSend = vi.fn();
      render(<FloatingInputBar value="Hello" onChange={vi.fn()} onSend={onSend} />);

      const input = screen.getByPlaceholderText(/message the agent/i);
      fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });

      expect(onSend).not.toHaveBeenCalled();
    });
  });

  describe('send button state', () => {
    it('disables send button when input is empty', () => {
      render(<FloatingInputBar value="" />);
      const sendButton = screen.getByTitle('Send message');
      expect(sendButton).toBeDisabled();
    });

    it('enables send button when input has text', () => {
      render(<FloatingInputBar value="Hello" />);
      const sendButton = screen.getByTitle('Send message');
      expect(sendButton).not.toBeDisabled();
    });

    it('shows stop button when disabled', () => {
      render(<FloatingInputBar disabled onStop={vi.fn()} />);
      expect(screen.getByTitle(/stop/i)).toBeInTheDocument();
      expect(screen.queryByTitle('Send message')).not.toBeInTheDocument();
    });
  });
});
