import { createPortal } from 'react-dom';

import { useI18n } from '../i18n';
import type { DesktopCommandPaletteInputV2 } from './DesktopCommandPaletteSurfaceV2';
import {
  projectDesktopCommandPaletteCompositionV2,
  type DesktopRendererCommandPaletteCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererCommandPaletteV2Props {
  readonly input: DesktopCommandPaletteInputV2;
}

export function DesktopRendererCommandPaletteV2({
  input,
}: DesktopRendererCommandPaletteV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const commandPalette = projectDesktopCommandPaletteCompositionV2(
    state.authority,
    composition,
  );
  if (commandPalette.status === 'ready') {
    const Surface = commandPalette.Surface;
    return <Surface input={input} />;
  }
  if (input.kind === 'hidden') return null;
  return <DesktopRendererCommandPaletteBoundaryV2 composition={commandPalette} />;
}

function DesktopRendererCommandPaletteBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererCommandPaletteCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return createPortal(
    <section
      className="desktop-production-route-boundary"
      data-command-palette-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      <h1>
        {t(
          loading
            ? 'desktopProductionRouter.loading.title'
            : 'desktopProductionRouter.unavailable.title',
        )}
      </h1>
      <p>
        {t(
          loading
            ? 'desktopProductionRouter.loading.description'
            : 'desktopProductionRouter.unavailable.description',
        )}
      </p>
    </section>,
    document.body,
  );
}
