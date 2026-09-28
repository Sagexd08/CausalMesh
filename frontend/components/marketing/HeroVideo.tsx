'use client';

import { useEffect, useRef } from 'react';
import { track } from '@/lib/analytics';

export const HERO_VIDEO =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260808_112712_da9d53df-6d27-4b12-bdf6-aa9dc2622bdf.mp4';

/**
 * The portal. `autoPlay` is in the server markup so playback starts before
 * hydration; the effect only handles the two cases markup cannot: a
 * visitor who asked for reduced motion (hold the first frame, which is the
 * poster), and a browser that refuses autoplay (keep the poster, report it).
 */
export function HeroVideo() {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => {
      if (reduced.matches) {
        video.pause();
        video.currentTime = 0;
      } else {
        video.play().catch((error: unknown) => {
          track('video_play_failure', {
            reason: error instanceof Error ? error.name : 'unknown',
          });
        });
      }
    };
    apply();
    reduced.addEventListener('change', apply);
    return () => reduced.removeEventListener('change', apply);
  }, []);

  return (
    <video
      ref={ref}
      className="enter-video"
      src={HERO_VIDEO}
      poster="/hero-poster.jpg"
      autoPlay
      muted
      loop
      playsInline
      preload="auto"
      aria-hidden="true"
      tabIndex={-1}
      onLoadedData={() => track('video_loaded')}
      onError={() => track('video_play_failure', { reason: 'load_error' })}
    />
  );
}
