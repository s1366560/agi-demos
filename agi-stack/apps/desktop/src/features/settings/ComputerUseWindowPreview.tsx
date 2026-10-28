import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ComputerUsePresentation } from '../../api/computerUseContractV2';
import type { ComputerUseInput } from '../../api/computerUseInput';
import { useI18n } from '../../i18n';
import type { ComputerUseInputStore } from './computerUseInputStore';
import {
  computerUseContainedImageBounds,
  computerUseCursorPosition,
  computerUseHeldLabels,
  computerUseInputMatchesPreview,
  type ImageBounds,
} from './computerUseInputPresentation';

const noSubscription = () => () => {};
const emptySnapshot = () => null;

/** Only this small preview subscribes to frame-rate input updates. */
export function ComputerUseWindowPreview({
  image,
  icon,
  presentation,
  sessionId,
  inputStore,
}: {
  image: string | null;
  icon: string | null;
  presentation: ComputerUsePresentation;
  sessionId?: string;
  inputStore?: ComputerUseInputStore | null;
}) {
  const { t } = useI18n();
  const subscribe = useCallback(
    (listener: () => void) =>
      inputStore && sessionId ? inputStore.subscribe(sessionId, listener) : noSubscription(),
    [inputStore, sessionId],
  );
  const getSnapshot = useCallback(
    () => (inputStore && sessionId ? inputStore.getSnapshot(sessionId) : null),
    [inputStore, sessionId],
  );
  const latest = useSyncExternalStore(subscribe, getSnapshot, emptySnapshot);
  const input = computerUseInputMatchesPreview(latest, presentation) ? latest : null;
  const element = useRef<HTMLImageElement>(null);
  const [measurement, setMeasurement] = useState<{
    image: string;
    bounds: ImageBounds | null;
  } | null>(null);
  useEffect(() => {
    const node = element.current;
    if (!node || !image) return;
    const measure = () =>
      setMeasurement({
        image,
        bounds: computerUseContainedImageBounds(
          node.clientWidth,
          node.clientHeight,
          node.naturalWidth,
          node.naturalHeight,
        ),
      });
    measure();
    node.addEventListener('load', measure);
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    resize?.observe(node);
    return () => {
      node.removeEventListener('load', measure);
      resize?.disconnect();
    };
  }, [image]);
  const point =
    input && image
      ? computerUseCursorPosition(input, measurement?.image === image ? measurement.bounds : null)
      : null;
  return (
    <>
      <div className="computer-use-window-preview">
        {image ? (
          <img
            ref={element}
            src={image}
            alt={t('cua.previewAlt', {
              app: presentation.target?.display_name ?? '',
            })}
          />
        ) : (
          <p>{t('cua.previewUnavailable')}</p>
        )}
        {point ? (
          <svg
            className="computer-use-virtual-cursor"
            viewBox="0 0 24 28"
            role="img"
            aria-label={t('cua.input.cursor')}
            style={{ transform: `translate(${point.x}px, ${point.y}px)` }}
          >
            <path d="M2 2v20l5-5 4 9 4-2-4-8h8Z" />
          </svg>
        ) : null}
        {image && icon ? (
          <img className="computer-use-preview-app-badge" src={icon} alt="" />
        ) : null}
      </div>
      {input ? <ComputerUseInputState input={input} /> : null}
    </>
  );
}

export function ComputerUseInputState({ input }: { input: ComputerUseInput }) {
  const { t } = useI18n();
  const held = computerUseHeldLabels(input);
  return (
    <div className="computer-use-input-state" aria-live="off" data-evidence={input.evidence}>
      <span title={input.evidence === 'dispatched' ? t('cua.input.dispatchedHint') : undefined}>
        {t(`cua.input.${input.evidence}`)}
      </span>
      <span>{t(`cua.input.${input.input_mode}`)}</span>
      <span className="computer-use-held-inputs" aria-label={t('cua.input.held')}>
        {held.length ? (
          held.map((label) => <kbd key={label}>{t(label)}</kbd>)
        ) : (
          <span>{t('cua.input.noneHeld')}</span>
        )}
      </span>
    </div>
  );
}
