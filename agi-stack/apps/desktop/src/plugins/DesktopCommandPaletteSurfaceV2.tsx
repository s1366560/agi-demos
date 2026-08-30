import type { ComponentProps } from 'react';
import { createPortal } from 'react-dom';

import { CommandPalette } from '../features/navigation/CommandPalette';

export type DesktopCommandPaletteInputV2 =
  | Readonly<{ kind: 'hidden' }>
  | Readonly<{
      kind: 'visible';
      props: Readonly<ComponentProps<typeof CommandPalette>>;
    }>;

export interface DesktopCommandPaletteSurfacePropsV2 {
  readonly input: DesktopCommandPaletteInputV2;
}

export function DesktopCommandPaletteSurfaceV2({
  input,
}: DesktopCommandPaletteSurfacePropsV2) {
  if (input.kind === 'hidden') return null;
  return createPortal(<CommandPalette {...input.props} />, document.body);
}
