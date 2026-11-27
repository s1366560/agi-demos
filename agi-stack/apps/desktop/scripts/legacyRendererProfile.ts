const profile = process.env.AGISTACK_DESKTOP_PROFILE;
export const compatibilityProfile = profile === 'compat';
/** Only the full profile. compat keeps its own shell and must not set this flag. */
export const fullDesktopProfile = profile === 'full';
/** The legacy business shell is gone. No profile compiles @business into the host. */
export const legacyBusinessProfile = false;

export const legacyRendererEntry = {
  name: 'desktop-profile-entry',
  transformIndexHtml: {
    order: 'pre' as const,
    handler(html: string) {
      if (!fullDesktopProfile) return html;
      return html.replace('/src/packageHost/main.tsx', '/src/fullHost/main.tsx');
    },
  },
};
