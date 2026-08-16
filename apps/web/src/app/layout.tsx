import type { Metadata } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans, Space_Grotesk } from "next/font/google";
import { AuthGate } from "@/components/organisms/AuthGate";
import { AppHeader } from "@/components/organisms/AppHeader";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: {
    default: "SRS Agent",
    template: "%s · SRS Agent",
  },
  description: "Import Azure DevOps backlogs and generate SRS documents",
};

// Runs before paint so the saved theme (light/dark + accent) applies with
// zero flash-of-wrong-theme.
const themeInitScript = `
(function() {
  try {
    // Light mode is the default — only an explicit prior choice
    // ('srs-agent-theme' in localStorage, set by ThemeToggle) switches to
    // dark. Deliberately NOT following prefers-color-scheme, so a fresh
    // visitor always lands on light regardless of their OS setting.
    var stored = localStorage.getItem('srs-agent-theme');
    var isDark = stored === 'dark';
    document.documentElement.classList.toggle('dark', isDark);
    var accent = localStorage.getItem('srs-agent-accent');
    if (accent) document.documentElement.dataset.accent = accent;
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${spaceGrotesk.variable} ${jakarta.variable} ${jetbrainsMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full flex flex-col bg-surface text-ink">
        <AppHeader />
        <main className="flex-1">
          <div className="mx-auto w-full max-w-4xl px-6 py-10 sm:py-14">
            <AuthGate>{children}</AuthGate>
          </div>
        </main>
      </body>
    </html>
  );
}
