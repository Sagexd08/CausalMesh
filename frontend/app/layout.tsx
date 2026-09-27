import { RootProvider } from 'fumadocs-ui/provider/next';
import './global.css';
import { Bricolage_Grotesque, JetBrains_Mono, Manrope, Outfit } from 'next/font/google';
import type { Metadata } from 'next';

// Matches the landing page. Inter, the scaffold default, is banned by the
// project's taste rules and flagged by its design detector as a face every
// AI product page converged on.
const body = Outfit({ subsets: ['latin'], variable: '--font-body' });
const display = Bricolage_Grotesque({
  subsets: ['latin'],
  variable: '--font-display-face',
});
// The site face. Variable, 200 to 800: the hero sets light display type and
// the technical surfaces set medium labels from the same file.
const site = Manrope({ subsets: ['latin'], variable: '--font-manrope', display: 'swap' });
const mono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono-face',
});

export const metadata: Metadata = {
  metadataBase: new URL('https://causalmesh.vercel.app'),
  title: 'CausalMesh — Coordination you can prove',
  description:
    'A coordination substrate for fleets of autonomous coding agents, with cryptographically verifiable evidence of everything every agent did.',
  openGraph: {
    title: 'CausalMesh — Coordination you can prove',
    description: 'Gate every action. Sign every action. Record every refusal with its reason.',
    images: ['/og-image.png'],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'CausalMesh — Coordination you can prove',
    description: 'Gate every action. Sign every action. Record every refusal with its reason.',
    images: ['/og-image.png'],
  },
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html
      lang="en"
      className={`${body.variable} ${display.variable} ${site.variable} ${mono.variable} ${body.className}`}
      suppressHydrationWarning
    >
      <body className="flex flex-col min-h-screen">
        {/* Dark by default so /docs continues the stage rather than cutting to
            white; the docs' own toggle still switches it. */}
        <RootProvider theme={{ defaultTheme: 'dark' }}>{children}</RootProvider>
      </body>
    </html>
  );
}
