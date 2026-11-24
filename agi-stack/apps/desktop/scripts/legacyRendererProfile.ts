const profile = process.env.AGISTACK_DESKTOP_PROFILE;
export const compatibilityProfile = profile === 'compat';
export const fullDesktopProfile = compatibilityProfile || profile === 'full';

export const legacyRendererEntry = {
  name: 'desktop-profile-entry',
  transformIndexHtml: {
    order: 'pre' as const,
    handler(html: string) {
      const entry = compatibilityProfile ? '/src/main.tsx' : '/src/fullHost/main.tsx';
      return html.replace('/src/packageHost/main.tsx', entry);
    },
  },
};
