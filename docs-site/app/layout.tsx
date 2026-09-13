import { RootProvider } from 'fumadocs-ui/provider/next';
import './global.css';
import { Bricolage_Grotesque, Outfit } from 'next/font/google';

// Matches the landing page. Inter, the scaffold default, is banned by the
// project's taste rules and flagged by its design detector as a face every
// AI product page converged on.
const body = Outfit({ subsets: ['latin'], variable: '--font-body' });
const display = Bricolage_Grotesque({
  subsets: ['latin'],
  variable: '--font-display',
});

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable} ${body.className}`} suppressHydrationWarning>
      <body className="flex flex-col min-h-screen">
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
