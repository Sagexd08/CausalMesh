/**
 * The mark: two offset slanted bars that read as an S and as a bolt.
 *
 * The brief calls for a supplied SVG that did not arrive with it. This is a
 * stand-in drawn to the same description; replace the two polygons with the
 * supplied geometry and nothing else needs to change. It stands alone,
 * with no wordmark beside it.
 */
export function BrandMark({ className = '', title = 'CausalMesh' }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 40 40"
      className={className}
      {...(title ? { role: 'img', 'aria-label': title } : { 'aria-hidden': true })}
    >
      <polygon points="15,2 38,2 27,19 4,19" fill="currentColor" />
      <polygon points="13,21 36,21 25,38 2,38" fill="currentColor" opacity="0.55" />
    </svg>
  );
}
