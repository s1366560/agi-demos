import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { errorText } from './marketRequest';
import type { MarketText } from './pluginMarketText';

interface Props {
  text: MarketText;
  title: string;
  confirmLabel: string;
  danger?: boolean;
  children: ReactNode;
  onConfirm(): Promise<void>;
  onClose(): void;
}
export function MarketDialog({
  text,
  title,
  confirmLabel,
  danger,
  children,
  onConfirm,
  onClose,
}: Props) {
  const node = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const titleId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const dialog = node.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  async function approve() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError('');
    try {
      await onConfirm();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  return (
    <dialog
      className="pm-dialog"
      ref={node}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h3 id={titleId}>{title}</h3>
      <div className="pm-dialog-body">{children}</div>
      {error && (
        <p role="alert" className="pm-error">
          {error}
        </p>
      )}
      <div className="pm-actions">
        <button type="button" className="pm-btn" disabled={busy} onClick={onClose}>
          {text.cancel}
        </button>
        <button
          type="button"
          disabled={busy}
          className={'pm-btn ' + (danger ? 'pm-danger' : 'pm-primary')}
          onClick={() => void approve()}
        >
          {busy ? text.changing : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
