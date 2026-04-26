import type { Metadata } from 'next';
import './globals.scss';

export const metadata: Metadata = {
  title: 'VoxRefiner — Live Display',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
