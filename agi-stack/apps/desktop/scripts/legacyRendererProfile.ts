const profile = process.env.AGISTACK_DESKTOP_PROFILE;
export const compatibilityProfile = profile === 'compat';
/** Only the full profile. compat keeps its own shell and must not set this flag. */
export const fullDesktopProfile = profile === 'full';
/** full and compat compile the legacy business shell. Unset and package-host do not. */
export const legacyBusinessProfile = fullDesktopProfile || compatibilityProfile;

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
