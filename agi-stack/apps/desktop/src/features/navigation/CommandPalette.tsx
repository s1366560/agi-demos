import type { ComponentProps } from 'react';
import { useDesktopRendererAuthorityV2 } from '../../plugins/desktopRendererAuthorityStateV2';
import { CommandPaletteSurface } from './CommandPaletteSurface';

export {
  groupCommandPaletteItems,
  getCommandPaletteFocusableElements,
} from './CommandPaletteSurface';

export function CommandPalette(
  props: Omit<ComponentProps<typeof CommandPaletteSurface>, 'shortcutIds'>,
) {
  const { shortcutIds } = useDesktopRendererAuthorityV2();
  return <CommandPaletteSurface {...props} shortcutIds={shortcutIds ?? []} />;
}
