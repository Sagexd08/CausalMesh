/**
 * Intent tracking with no vendor attached.
 *
 * Events describe what a visitor did ("hero_cta", "code_copy"), not which
 * element fired. Each one is pushed to `window.dataLayer` when a tag
 * manager has installed one, and dispatched as a `site:track` DOM event
 * either way, so an analytics provider can be wired later without
 * touching a component. With nothing listening, it costs one array push.
 */

export type TrackEvent =
  | 'hero_cta'
  | 'architecture_click'
  | 'architecture_route'
  | 'gate_example'
  | 'docs_click'
  | 'github_click'
  | 'code_copy'
  | 'demo_interaction'
  | 'benchmark_filter'
  | 'research_click'
  | 'faq_open'
  | 'menu_open'
  | 'menu_cta'
  | 'video_loaded'
  | 'video_play_failure';

type Props = Record<string, string | number | boolean | undefined>;

declare global {
  interface Window {
    dataLayer?: Array<Record<string, unknown>>;
  }
}

export function track(event: TrackEvent, props: Props = {}): void {
  if (typeof window === 'undefined') return;
  try {
    window.dataLayer?.push({ event, ...props });
    window.dispatchEvent(new CustomEvent('site:track', { detail: { event, ...props } }));
  } catch {
    // Tracking must never be the reason an interaction fails.
  }
}
