import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

type Theme = 'light' | 'dark' | 'system' | 'high-contrast';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  computedTheme: 'light' | 'dark'; // The actual theme being applied
}

export const useThemeStore = create<ThemeState>()(
  devtools(
    persist(
      (set) => ({
        theme: 'system',
        computedTheme: 'light', // Default initial
        setTheme: (theme) => {
          set({ theme });
          updateDocumentClass(theme);
        },
      }),
      {
        name: 'theme-storage',
        onRehydrateStorage: () => (state) => {
          if (state) {
            updateDocumentClass(state.theme);
          }
        },
      }
    ),
    {
      name: 'ThemeStore',
      enabled: import.meta.env.DEV,
    }
  )
);

const updateDocumentClass = (theme: Theme) => {
  const root = window.document.documentElement;

  if (theme === 'high-contrast') {
    root.classList.add('dark', 'high-contrast');
    useThemeStore.setState({ computedTheme: 'dark' });
    setThemeColorMeta('dark');
    return;
  }

  root.classList.remove('high-contrast');
  const isDark =
    theme === 'dark' ||
    (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);

  if (isDark) {
    root.classList.add('dark');
    useThemeStore.setState({ computedTheme: 'dark' });
  } else {
    root.classList.remove('dark');
    useThemeStore.setState({ computedTheme: 'light' });
  }
  setThemeColorMeta(isDark ? 'dark' : 'light');
};

/** Keep the `<meta name="theme-color">` (browser chrome / mobile address bar)
 * in sync with the active theme. index.html ships a `prefers-color-scheme`-
 * scoped pair for correct pre-JS rendering; an explicit user choice needs a
 * media-less override tag, which always matches and therefore wins. */
const setThemeColorMeta = (mode: 'light' | 'dark') => {
  const value = mode === 'dark' ? '#080c12' : '#ffffff';
  let plain = Array.from(
    document.head.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
  ).find((m) => !m.hasAttribute('media'));
  if (!plain) {
    plain = document.createElement('meta');
    plain.setAttribute('name', 'theme-color');
    document.head.appendChild(plain);
  }
  plain.setAttribute('content', value);
};

// Listen for system changes if theme is 'system'
if (typeof window !== 'undefined') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const { theme } = useThemeStore.getState();
    if (theme === 'system') {
      updateDocumentClass('system');
    }
  });
}
