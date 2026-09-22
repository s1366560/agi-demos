import './ConversationToolbar.css';
import { createContext, useContext, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export const ConversationToolbarContext = createContext<HTMLElement | null>(
  null,
);

/** Share one action row without moving ownership of conversation tools. */
export function ConversationToolbarItem({ children }: { children: ReactNode }) {
  const host = useContext(ConversationToolbarContext);
  return host ? createPortal(children, host) : <>{children}</>;
}

export const TitlebarToolbarContext = createContext<{
  host: HTMLDivElement | null;
  setHost: (host: HTMLDivElement | null) => void;
} | null>(null);

export function TitlebarToolbarProvider({ children }: { children: ReactNode }) {
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  return (
    <TitlebarToolbarContext.Provider value={{ host, setHost }}>
      {children}
    </TitlebarToolbarContext.Provider>
  );
}
