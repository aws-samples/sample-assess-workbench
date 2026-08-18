import { useState, useCallback, useEffect } from 'preact/hooks';

const STORAGE_KEY = 'theme';
const THEMES = ['dark', 'light'];

function getInitialTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && THEMES.includes(stored)) return stored;
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
  return 'dark';
}

export function useTheme() {
  const [theme, setThemeState] = useState(getInitialTheme);

  const setTheme = useCallback((t) => {
    if (THEMES.includes(t)) {
      localStorage.setItem(STORAGE_KEY, t);
      document.documentElement.setAttribute('data-theme', t);
      setThemeState(t);
    }
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  // Sync on mount
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, []);

  return { theme, toggle };
}
