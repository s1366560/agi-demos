export function settingsShellMessages(locale: string) {
  return locale.startsWith('zh')
    ? { integrations: '工具与集成' }
    : { integrations: 'Tools & integrations' };
}
