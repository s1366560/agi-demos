import {
  sessionTimelineFollowIntent,
  timelineScrollFrame,
} from './sessionTimelineScrollModel';

const rowSelector = '[data-timeline-anchor-id]';
const paragraphSelector = 'p, pre, li, tr, h1, h2, h3, h4, h5, h6';

export function timelineAnchorMemberIds(anchor: HTMLElement): string[] {
  try {
    const members: unknown = JSON.parse(anchor.dataset.timelineAnchorMembers ?? '[]');
    return Array.isArray(members) && members.every((id) => typeof id === 'string') ? members : [];
  } catch {
    return [];
  }
}

export function findTimelineAnchor(viewport: HTMLElement, id: string) {
  const exact = viewport.querySelector<HTMLElement>(
    `[data-timeline-anchor-id="${CSS.escape(id)}"]`
  );
  if (exact && exact.getClientRects().length) return exact;
  return Array.from(viewport.querySelectorAll<HTMLElement>('[data-timeline-anchor-members]')).find(
    (row) => timelineAnchorMemberIds(row).includes(id) && row.getClientRects().length
  );
}

function captureReadingPosition(viewport: HTMLElement) {
  const bounds = viewport.getBoundingClientRect();
  // Hit testing usually locates the passage immediately, including in very long transcripts.
  // A gap between rows or a toolbar over the text needs the geometry fallback.
  const hit = viewport.ownerDocument
    .elementsFromPoint(bounds.left + bounds.width / 2, bounds.top + 2)
    .find((element) => viewport.contains(element) && element.closest(rowSelector));
  const row =
    hit?.closest<HTMLElement>(rowSelector) ??
    Array.from(viewport.querySelectorAll<HTMLElement>(rowSelector)).find((candidate) => {
      const rect = candidate.getBoundingClientRect();
      return rect.height > 0 && rect.bottom > bounds.top + 1 && rect.top < bounds.bottom;
    });
  if (!row) return null;
  const paragraphs = Array.from(row.querySelectorAll<HTMLElement>(paragraphSelector));
  const visibleParagraph = hit?.closest<HTMLElement>(paragraphSelector);
  const index =
    visibleParagraph && row.contains(visibleParagraph)
      ? paragraphs.indexOf(visibleParagraph)
      : paragraphs.findIndex((paragraph) => {
          const rect = paragraph.getBoundingClientRect();
          return rect.height > 0 && rect.bottom > bounds.top + 1 && rect.top < bounds.bottom;
        });
  const element = paragraphs[index] ?? row;
  return {
    element,
    index,
    id: row.dataset.timelineAnchorId ?? '',
    member: timelineAnchorMemberIds(row)[0],
    offset: element.getBoundingClientRect().top - bounds.top,
  };
}

function ownsNestedScroll(target: EventTarget | null, viewport: HTMLElement) {
  if (!(target instanceof Element)) return false;
  for (let node: Element | null = target; node && node !== viewport; node = node.parentElement) {
    if (node.scrollHeight <= node.clientHeight) continue;
    const overflow = getComputedStyle(node).overflowY;
    if (overflow === 'auto' || overflow === 'scroll') return true;
  }
  return false;
}

/** One controller per mounted conversation viewport, including its Radix scrollbar. */
export function mountTranscriptViewport(
  viewport: HTMLElement,
  onFollowingChange: (following: boolean) => void,
  onHistoryEdge: () => void,
  allowHistoryNavigation?: () => boolean
) {
  let following = true;
  const { schedule, cancel: cancelFrame } = timelineScrollFrame(reconcile);
  let reading: ReturnType<typeof captureReadingPosition> = null;
  let navigation: { id: string; onLocated: (target: HTMLElement) => void } | null = null;
  let lastTop = viewport.scrollTop;
  let lastWriteFrame: DocumentTimeline['currentTime'] = null;
  let direction: 'forward' | 'backward' | null = null;
  let gestureMoved = false;
  let tabPressed = false;
  let dragging = false;
  let touchY: number | null = null;

  function setFollowing(next: boolean) {
    if (following === next) return;
    following = next;
    onFollowingChange(next);
  }
  function reconcile() {
    // Chromium can apply a compositor scroll before dispatching its scroll event.
    // Accept that movement before using an anchor captured by the preceding frame.
    acceptUserMovement();
    let nextTop = viewport.scrollTop;
    const pending = navigation;
    const target = pending && findTimelineAnchor(viewport, pending.id);
    if (target) {
      const rect = target.getBoundingClientRect();
      nextTop +=
        rect.top - viewport.getBoundingClientRect().top + (rect.height - viewport.clientHeight) / 2;
    } else if (following) {
      nextTop = viewport.scrollHeight - viewport.clientHeight;
    } else if (reading) {
      let element: HTMLElement | undefined = reading.element;
      if (!viewport.contains(element) || !element.getClientRects().length) {
        const row =
          findTimelineAnchor(viewport, reading.id) ??
          (reading.member ? findTimelineAnchor(viewport, reading.member) : undefined);
        const paragraphs = row?.querySelectorAll<HTMLElement>(paragraphSelector);
        // Markdown finalization may insert blocks before a remounted paragraph.
        const previousText = element.textContent;
        const sameText =
          previousText &&
          paragraphs &&
          Array.from(paragraphs).find((paragraph) => paragraph.textContent === previousText);
        element = sameText || paragraphs?.[reading.index] || row;
      }
      if (element) {
        reading.element = element;
        nextTop +=
          element.getBoundingClientRect().top -
          viewport.getBoundingClientRect().top -
          reading.offset;
      } else {
        reading = null;
      }
    }
    const boundedTop = Math.max(
      0,
      Math.min(nextTop, viewport.scrollHeight - viewport.clientHeight)
    );
    if (Math.abs(boundedTop - viewport.scrollTop) > 0.5) {
      const timestamp = viewport.ownerDocument.timeline?.currentTime;
      if (timestamp != null && lastWriteFrame === timestamp) {
        schedule();
        return;
      }
      viewport.scrollTop = boundedTop;
      lastWriteFrame = timestamp ?? null;
    }
    lastTop = viewport.scrollTop;
    if (target && pending) {
      navigation = null;
      reading = null;
      pending.onLocated(target);
    }
    if (!following && !reading) reading = captureReadingPosition(viewport);
  }
  function followLatest() {
    navigation = null;
    reading = null;
    direction = null;
    setFollowing(true);
    schedule();
  }
  function navigate(id: string, onLocated: (target: HTMLElement) => void) {
    const request = { id, onLocated };
    navigation = request;
    reading = null;
    direction = null;
    setFollowing(false);
    schedule();
    return () => {
      if (navigation === request) navigation = null;
    };
  }
  function readHere() {
    cancelFrame();
    navigation = null;
    setFollowing(false);
    reading = captureReadingPosition(viewport);
  }
  function input(next: 'forward' | 'backward') {
    cancelFrame();
    navigation = null;
    direction = next;
    gestureMoved = false;
    if (next === 'backward' && following) readHere();
    if (next === 'forward' && sessionTimelineFollowIntent(following, next, viewport)) {
      setFollowing(true);
      reading = null;
    }
    if (following) schedule();
  }
  function wheel(event: WheelEvent) {
    if (!event.ctrlKey && event.deltaY !== 0 && !ownsNestedScroll(event.target, viewport)) {
      input(event.deltaY < 0 ? 'backward' : 'forward');
    }
  }
  function keyDown(event: KeyboardEvent) {
    if (
      event.defaultPrevented ||
      event.metaKey ||
      event.altKey ||
      event.ctrlKey ||
      ownsNestedScroll(event.target, viewport) ||
      (event.target instanceof Element &&
        event.target.closest(
          'input, textarea, select, [contenteditable="true"], button, a, summary'
        ))
    )
      return;
    if (
      ['ArrowUp', 'PageUp', 'Home'].includes(event.key) ||
      (event.key === ' ' && event.shiftKey)
    ) {
      input('backward');
    } else if (['ArrowDown', 'PageDown', 'End', ' '].includes(event.key)) {
      input('forward');
    }
  }
  function touchStart(event: TouchEvent) {
    touchY = ownsNestedScroll(event.target, viewport) ? null : (event.touches[0]?.clientY ?? null);
  }
  function touchMove(event: TouchEvent) {
    const next = event.touches[0]?.clientY;
    if (touchY !== null && next !== undefined && next !== touchY) {
      input(next > touchY ? 'backward' : 'forward');
      touchY = next;
    }
  }
  function pointerDown(event: PointerEvent) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const bar = target.closest('.rt-ScrollAreaScrollbar[data-orientation="vertical"]');
    const draggingBar = Boolean(bar && bar.closest('.rt-ScrollAreaRoot') === root);
    dragging = draggingBar || (viewport.contains(target) && !ownsNestedScroll(target, viewport));
    if (draggingBar) readHere();
  }
  function pointerUp() {
    dragging = false;
  }
  function trackTab(event: KeyboardEvent) {
    if (event.key !== 'Tab') return;
    if (event.type === 'keyup') acceptUserMovement();
    tabPressed = event.type === 'keydown';
  }
  function scrollEnd() {
    // A scrollend from our previous correction can arrive between a wheel event
    // and the compositor's first movement for the new gesture.
    if (gestureMoved) direction = null;
  }
  function acceptUserMovement() {
    const moved = viewport.scrollTop - lastTop;
    if (!moved) return false;
    lastTop = viewport.scrollTop;
    const source = moved < 0 ? 'backward' : 'forward';
    if (tabPressed && viewport.contains(viewport.ownerDocument.activeElement)) direction = source;
    // A browser can scroll a focused disclosure or a search match into view
    // without a wheel gesture. A completed Web transcript is readable history.
    const browsingHistory = source === 'backward' && allowHistoryNavigation?.();
    if (dragging || direction === source || browsingHistory) {
      if (source === direction) gestureMoved = true;
      setFollowing(sessionTimelineFollowIntent(following, source, viewport));
      reading = following ? null : captureReadingPosition(viewport);
      if (following) schedule();
      if (source === 'backward' && viewport.scrollTop <= 96) onHistoryEdge();
      return false;
    }
    // Scrolling to a focused element or browser layout can move the viewport
    // without a gesture. Keep the current anchor and stop any implicit smooth scroll.
    return true;
  }
  function scroll() {
    if (acceptUserMovement()) reconcile();
  }

  // Intrinsic image sizes and disclosures can change after rAF, before paint.
  const observer = new ResizeObserver(reconcile);
  observer.observe(viewport);
  if (viewport.firstElementChild) observer.observe(viewport.firstElementChild);
  viewport.addEventListener('scroll', scroll, { passive: true });
  viewport.addEventListener('scrollend', scrollEnd);
  viewport.addEventListener('wheel', wheel, { passive: true });
  viewport.addEventListener('touchstart', touchStart, { passive: true });
  viewport.addEventListener('touchmove', touchMove, { passive: true });
  viewport.addEventListener('keydown', keyDown);
  const root = viewport.closest('.rt-ScrollAreaRoot') ?? viewport;
  root.addEventListener('pointerdown', pointerDown as EventListener, true);
  window.addEventListener('pointerup', pointerUp);
  window.addEventListener('pointercancel', pointerUp);
  window.addEventListener('keydown', trackTab, true);
  window.addEventListener('keyup', trackTab, true);
  onFollowingChange(true);
  schedule();
  return {
    schedule,
    followLatest,
    readHere,
    navigate,
    dispose() {
      observer.disconnect();
      cancelFrame();
      viewport.removeEventListener('scroll', scroll);
      viewport.removeEventListener('scrollend', scrollEnd);
      viewport.removeEventListener('wheel', wheel);
      viewport.removeEventListener('touchstart', touchStart);
      viewport.removeEventListener('touchmove', touchMove);
      viewport.removeEventListener('keydown', keyDown);
      root.removeEventListener('pointerdown', pointerDown as EventListener, true);
      window.removeEventListener('pointerup', pointerUp);
      window.removeEventListener('pointercancel', pointerUp);
      window.removeEventListener('keydown', trackTab, true);
      window.removeEventListener('keyup', trackTab, true);
    },
  };
}
