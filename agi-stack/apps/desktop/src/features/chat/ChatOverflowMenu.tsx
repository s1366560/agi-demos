import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { DotsHorizontalIcon } from '@radix-ui/react-icons';

/** Keeps secondary tools mounted so their dialogs survive disclosure changes. */
export function ChatOverflowMenu({
  label,
  className = '',
  icon,
  forceOpen = false,
  children,
}: {
  label: string;
  className?: string;
  icon?: ReactNode;
  forceOpen?: boolean;
  children: ReactNode;
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (forceOpen && detailsRef.current) detailsRef.current.open = true;
  }, [forceOpen]);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      const details = detailsRef.current;
      if (
        details?.open &&
        event.target instanceof Node &&
        !details.contains(event.target)
      ) {
        details.open = false;
      }
    };
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, []);

  return (
    <details
      ref={detailsRef}
      data-attention={forceOpen || undefined}
      className={`chat-overflow-menu ${className}`}
      onKeyDown={(event) => {
        if (
          event.key !== 'Escape' ||
          !event.currentTarget.contains(event.target as Node)
        )
          return;
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.open = false;
        event.currentTarget.querySelector('summary')?.focus();
      }}
    >
      <summary aria-label={label} title={label}>
        {icon ?? <DotsHorizontalIcon aria-hidden="true" />}
      </summary>
      <div
        className="chat-overflow-menu-content"
        role="group"
        aria-label={label}
      >
        {children}
      </div>
    </details>
  );
}
