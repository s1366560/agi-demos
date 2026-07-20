import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { AppModal } from '@/components/common/AppModal';

describe('AppModal', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.body.style.overflow = '';
  });
  afterEach(() => cleanup());

  it('renders nothing when open=false', () => {
    render(<AppModal open={false} onClose={() => {}} title="t">body</AppModal>);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it('renders dialog with aria-modal and aria-labelledby pointing at the title', () => {
    render(
      <AppModal open onClose={() => {}} title="My Title">
        body
      </AppModal>
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const titleEl = document.getElementById(labelledBy!);
    expect(titleEl?.textContent).toContain('My Title');
  });

  it('uses aria-label when no title is provided', () => {
    render(
      <AppModal open onClose={() => {}} ariaLabel="Accessible name">
        body
      </AppModal>
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-label')).toBe('Accessible name');
    expect(dialog.getAttribute('aria-labelledby')).toBeFalsy();
  });

  it('locks body scroll while open and restores on close', () => {
    document.body.style.overflow = 'visible';
    const { rerender } = render(
      <AppModal open onClose={() => {}} title="t">
        body
      </AppModal>
    );
    expect(document.body.style.overflow).toBe('hidden');
    rerender(
      <AppModal open={false} onClose={() => {}} title="t">
        body
      </AppModal>
    );
    expect(document.body.style.overflow).toBe('visible');
  });

  it('closes on Escape key', () => {
    const onClose = vi.fn();
    render(
      <AppModal open onClose={onClose} title="t">
        body
      </AppModal>
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does NOT close on Escape when isDirty=true and user declines confirm', () => {
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <AppModal open onClose={onClose} title="t" isDirty>
        body
      </AppModal>
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('closes when backdrop is clicked', () => {
    const onClose = vi.fn();
    render(
      <AppModal open onClose={onClose} title="t">
        body
      </AppModal>
    );
    const overlay = document.querySelector('.app-modal') as HTMLElement;
    fireEvent.mouseDown(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does NOT close when clicking inside the panel', () => {
    const onClose = vi.fn();
    render(
      <AppModal open onClose={onClose} title="t">
        <button>inner</button>
      </AppModal>
    );
    fireEvent.mouseDown(screen.getByText('inner'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('restores focus to the previously focused element on close', () => {
    const trigger = document.createElement('button');
    trigger.textContent = 'trigger';
    document.body.appendChild(trigger);
    const focusSpy = vi.spyOn(trigger, 'focus');
    trigger.focus();

    const { rerender } = render(
      <AppModal open onClose={() => {}} title="t">
        body
      </AppModal>
    );
    expect(screen.getByRole('dialog')).toBeTruthy();

    rerender(
      <AppModal open={false} onClose={() => {}} title="t">
        body
      </AppModal>
    );
    // Cleanup effect calls focus() on the previously focused element.
    expect(focusSpy).toHaveBeenCalled();
    document.body.removeChild(trigger);
  });

  it('traps Tab focus within the dialog (wraps from last to first focusable)', () => {
    render(
      <AppModal open onClose={() => {}} title="t">
        <button>first</button>
        <button>second</button>
      </AppModal>
    );
    const dialog = screen.getByRole('dialog');
    const secondBtn = screen.getByText('second');
    secondBtn.focus();
    expect(document.activeElement).toBe(secondBtn);
    fireEvent.keyDown(document, { key: 'Tab' });
    // Focus must stay inside the dialog and wrap backward (not escape to body).
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(secondBtn);
  });
});
