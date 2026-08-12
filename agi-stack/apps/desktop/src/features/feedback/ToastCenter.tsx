import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { Cross2Icon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  createToastIdFactory,
  dismissToastFromQueue,
  enqueueToast,
  toastAriaRole,
  toastDismissDelay,
  type Toast,
  type ToastIdFactory,
  type ToastKind,
} from './toastModel';
import './ToastCenter.css';

type ToastContextValue = {
  showToast: (kind: ToastKind, message: string, detail?: string) => void;
  dismissToast: (id: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used inside ToastProvider');
  return context;
}

export function ToastViewport({
  toasts,
  onDismiss,
  exitingIds,
}: {
  toasts: readonly Toast[];
  onDismiss: (id: string) => void;
  exitingIds?: ReadonlySet<string>;
}) {
  const { t } = useI18n();
  return (
    <section className="toast-viewport" aria-label={t('toast.viewportLabel')} aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast toast--${toast.kind}${exitingIds?.has(toast.id) ? ' toast-exiting' : ''}`}
          role={toastAriaRole(toast.kind)}
          aria-live={toast.kind === 'error' ? 'assertive' : undefined}
        >
          <span className="toast__accent" aria-hidden="true" />
          <div className="toast__body">
            <p className="toast__message">{toast.message}</p>
            {toast.detail ? <p className="toast__detail">{toast.detail}</p> : null}
          </div>
          <button
            type="button"
            className="toast__dismiss"
            aria-label={t('toast.dismiss')}
            title={t('toast.dismiss')}
            onClick={() => onDismiss(toast.id)}
          >
            <Cross2Icon aria-hidden="true" />
          </button>
        </div>
      ))}
    </section>
  );
}

const TOAST_EXIT_MS = 140;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly Toast[]>([]);
  const [exitingIds, setExitingIds] = useState<ReadonlySet<string>>(new Set());
  const idFactoryRef = useRef<ToastIdFactory | null>(null);
  if (idFactoryRef.current === null) {
    idFactoryRef.current = createToastIdFactory();
  }
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const exitTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismissToast = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    if (exitTimersRef.current.has(id)) return;
    setExitingIds((current) => new Set(current).add(id));
    exitTimersRef.current.set(
      id,
      setTimeout(() => {
        exitTimersRef.current.delete(id);
        setExitingIds((current) => {
          if (!current.has(id)) return current;
          const next = new Set(current);
          next.delete(id);
          return next;
        });
        setToasts((current) => dismissToastFromQueue(current, id));
      }, TOAST_EXIT_MS),
    );
  }, []);

  const showToast = useCallback(
    (kind: ToastKind, message: string, detail?: string) => {
      const id = (idFactoryRef.current ?? createToastIdFactory())();
      const toast: Toast = detail ? { id, kind, message, detail } : { id, kind, message };
      setToasts((current) => enqueueToast(current, toast));
      timersRef.current.set(
        id,
        setTimeout(() => dismissToast(id), toastDismissDelay(kind)),
      );
    },
    [dismissToast],
  );

  useEffect(
    () => () => {
      for (const timer of timersRef.current.values()) clearTimeout(timer);
      timersRef.current.clear();
      for (const timer of exitTimersRef.current.values()) clearTimeout(timer);
      exitTimersRef.current.clear();
    },
    [],
  );

  const value = useMemo<ToastContextValue>(
    () => ({ showToast, dismissToast }),
    [showToast, dismissToast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      {typeof document === 'undefined'
        ? null
        : createPortal(
            <ToastViewport toasts={toasts} exitingIds={exitingIds} onDismiss={dismissToast} />,
            document.body,
          )}
    </ToastContext.Provider>
  );
}
