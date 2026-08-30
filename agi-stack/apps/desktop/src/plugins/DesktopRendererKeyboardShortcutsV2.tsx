import { useI18n } from '../i18n';
import type { DesktopKeyboardShortcutsInputV2 } from './DesktopKeyboardShortcutsSurfaceV2';
import {
  projectDesktopKeyboardShortcutsCompositionV2,
  type DesktopRendererKeyboardShortcutsCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererKeyboardShortcutsV2Props {
  readonly input: DesktopKeyboardShortcutsInputV2;
}

export function DesktopRendererKeyboardShortcutsV2({
  input,
}: DesktopRendererKeyboardShortcutsV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const keyboardShortcuts = projectDesktopKeyboardShortcutsCompositionV2(
    state.authority,
    composition,
  );
  if (keyboardShortcuts.status === 'ready') {
    const Surface = keyboardShortcuts.Surface;
    return <Surface input={input} />;
  }
  if (!input.open) return null;
  return <DesktopRendererKeyboardShortcutsBoundaryV2 composition={keyboardShortcuts} />;
}

function DesktopRendererKeyboardShortcutsBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererKeyboardShortcutsCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-keyboard-shortcuts-state={composition.status}
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
    </section>
  );
}
