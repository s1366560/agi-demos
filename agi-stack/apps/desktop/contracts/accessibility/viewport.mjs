export function deriveZoomEquivalentViewport(referenceViewport, zoomFactor) {
  const width = Number(referenceViewport?.width);
  const height = Number(referenceViewport?.height);
  const factor = Number(zoomFactor);
  if (
    !Number.isFinite(width) ||
    width <= 0 ||
    !Number.isFinite(height) ||
    height <= 0 ||
    !Number.isFinite(factor) ||
    factor <= 0
  ) {
    throw new Error("accessibility_zoom_factor_invalid");
  }
  return Object.freeze({
    referenceWidth: width,
    referenceHeight: height,
    zoomFactor: factor,
    width: Math.floor(width / factor),
    height: Math.floor(height / factor),
  });
}
