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
}: {
  toasts: readonly Toast[];
  onDismiss: (id: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="toast-viewport" aria-label={t('toast.viewportLabel')} aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast toast--${toast.kind}`}
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
            onClick={() => onDismiss(toast.id)}
          >
            <Cross2Icon aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly Toast[]>([]);
  const idFactoryRef = useRef<ToastIdFactory | null>(null);
  if (idFactoryRef.current === null) {
    idFactoryRef.current = createToastIdFactory();
  }
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismissToast = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setToasts((current) => dismissToastFromQueue(current, id));
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
        : createPortal(<ToastViewport toasts={toasts} onDismiss={dismissToast} />, document.body)}
    </ToastContext.Provider>
  );
}
