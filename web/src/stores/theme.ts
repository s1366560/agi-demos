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
          const computedTheme = updateDocumentClass(theme);
          set({ theme, computedTheme });
        },
      }),
      {
        name: 'theme-storage',
        partialize: (state) => ({ theme: state.theme }),
        onRehydrateStorage: () => (state) => {
          if (state) {
            // Hydration can run before create() returns. Use the action's
            // captured setter instead of reading the uninitialized store export.
            state.setTheme(state.theme);
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

function updateDocumentClass(theme: Theme): 'light' | 'dark' {
  const root = window.document.documentElement;

  if (theme === 'high-contrast') {
    root.classList.add('dark', 'high-contrast');
    setThemeColorMeta('dark');
    return 'dark';
  }

  root.classList.remove('high-contrast');
  const isDark =
    theme === 'dark' ||
    (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);

  if (isDark) {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
  setThemeColorMeta(isDark ? 'dark' : 'light');
  return isDark ? 'dark' : 'light';
}

/** Keep the `<meta name="theme-color">` (browser chrome / mobile address bar)
 * in sync with the active theme. index.html ships a `prefers-color-scheme`-
 * scoped pair for correct pre-JS rendering; an explicit user choice needs a
 * media-less override tag, which always matches and therefore wins. */
function setThemeColorMeta(mode: 'light' | 'dark') {
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
}

// Listen for system changes if theme is 'system'
if (typeof window !== 'undefined') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const { theme, setTheme } = useThemeStore.getState();
    if (theme === 'system') {
      setTheme('system');
    }
  });
}
