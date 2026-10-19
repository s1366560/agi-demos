import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

export const OPEN_COMMAND_PALETTE_EVENT_V2 = 'memstack:open-command-palette';
export function openCommandPaletteV2(): void {
  document.dispatchEvent(new Event(OPEN_COMMAND_PALETTE_EVENT_V2));
}

/** Manages the global Cmd/Ctrl+K listener and command-palette visibility. */
export function useCommandPaletteOpen(): [boolean, Dispatch<SetStateAction<boolean>>] {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault();
        setOpen((previous) => !previous);
      }
    };
    const open = () => {
      setOpen(true);
    };
    document.addEventListener(OPEN_COMMAND_PALETTE_EVENT_V2, open);
    document.addEventListener('keydown', handler);
    return () => {
      document.removeEventListener(OPEN_COMMAND_PALETTE_EVENT_V2, open);
      document.removeEventListener('keydown', handler);
    };
  }, []);

  return [open, setOpen];
}
