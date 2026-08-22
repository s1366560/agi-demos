import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

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
    document.addEventListener('keydown', handler);
    return () => {
      document.removeEventListener('keydown', handler);
    };
  }, []);

  return [open, setOpen];
}
