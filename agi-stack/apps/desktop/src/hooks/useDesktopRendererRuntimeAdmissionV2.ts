import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';

/** Admit runtime requests only while an authenticated renderer generation is committed. */
export function useDesktopRendererRuntimeAdmissionV2(
  authenticated: boolean,
  generationDigest: string | undefined,
  onReady: () => void
): () => boolean {
  const admittedRef = useRef(false);
  const onReadyRef = useRef(onReady);

  useLayoutEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  useLayoutEffect(() => {
    admittedRef.current = authenticated && generationDigest !== undefined;
    return () => {
      admittedRef.current = false;
    };
  }, [authenticated, generationDigest]);

  useEffect(() => {
    if (authenticated && generationDigest !== undefined) onReadyRef.current();
  }, [authenticated, generationDigest]);

  return useCallback(() => admittedRef.current, []);
}
