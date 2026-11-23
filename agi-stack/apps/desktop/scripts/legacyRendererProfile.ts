export const fullDesktopProfile = process.env.AGISTACK_DESKTOP_PROFILE === 'full';

export const legacyRendererEntry = {
  name: 'legacy-desktop-entry',
  transformIndexHtml: {
    order: 'pre' as const,
    handler(html: string) {
      return html.replace('/src/packageHost/main.tsx', '/src/main.tsx');
    },
  },
};
