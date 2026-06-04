// ThemeToggle.tsx — the sun/moon light/dark switch (topbar + login).
//
// Reads/flips the theme via useThemeStore. Shows the icon of the theme it will
// switch TO (a sun in dark mode → "go light"; a moon in light mode → "go dark"),
// which is the common affordance. The store mutator applies the <html> class and
// persists, so this is purely presentational.

import { Moon, Sun } from 'lucide-react';

import { useThemeStore } from '@/stores/theme';

export function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const isDark = theme === 'dark';

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Light mode' : 'Dark mode'}
      className="inline-flex size-8 cursor-pointer items-center justify-center rounded-md border border-border text-text-secondary transition-colors hover:border-primary hover:text-primary"
    >
      {isDark ? (
        <Sun className="size-[15px]" aria-hidden="true" />
      ) : (
        <Moon className="size-[15px]" aria-hidden="true" />
      )}
    </button>
  );
}
