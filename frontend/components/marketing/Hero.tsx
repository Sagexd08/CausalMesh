import type { CSSProperties } from 'react';
import { SiteNav } from '@/components/layout/SiteNav';
import { TrackedLink } from '@/components/ui/TrackedLink';
import { LINKS, STRIP } from '@/lib/site/content';
import { HeroVideo } from './HeroVideo';

/**
 * The first viewport is one composition: mark, navigation, headline,
 * subcopy, two actions, the portal, and the strip. Nothing else. The
 * technical density starts one scroll below, on purpose.
 */
export function Hero() {
  return (
    <header className="hero">
      <div className="hero-plate">
        <HeroVideo />
      </div>

      <SiteNav />

      <div className="hero-copy">
        <h1 className="hero-title enter" style={{ '--i': 2 } as CSSProperties}>
          The Next Layer
          <br />
          of Intelligence
        </h1>
        <p className="hero-sub enter" style={{ '--i': 3 } as CSSProperties}>
          The accountability layer underneath AI agents. Every action gated,
          signed, and recorded, with every refusal kept alongside its reason.
        </p>
        <div className="hero-ctas enter" style={{ '--i': 4 } as CSSProperties}>
          <TrackedLink
            event="hero_cta"
            props={{ cta: 'get_started' }}
            href={LINKS.quickstart}
            className="pill"
          >
            Get Started
          </TrackedLink>
          <TrackedLink
            event="architecture_click"
            props={{ placement: 'hero' }}
            href={LINKS.architecture}
            className="ghost"
          >
            View Architecture <span aria-hidden="true">&rarr;</span>
          </TrackedLink>
        </div>
      </div>

      <div className="hero-strip enter" style={{ '--i': 5 } as CSSProperties}>
        <span className="hero-strip-label">Any OpenAI-compatible client</span>
        {STRIP.map((name) => (
          <span key={name} className="hero-strip-mark">
            {name}
          </span>
        ))}
      </div>
    </header>
  );
}
