import { Cross2Icon } from '@radix-ui/react-icons';
import type { ReactNode } from 'react';

export function Dialog({
  children,
  title,
  onClose,
}: {
  children: ReactNode;
  title: string;
  onClose: () => void;
}) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="dialog-card" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><span>MEMSTACK</span><h2>{title}</h2></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close dialog"><Cross2Icon /></button>
        </header>
        {children}
      </section>
    </div>
  );
}
