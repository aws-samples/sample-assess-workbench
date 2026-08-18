import { createContext } from 'preact';
import { useState, useEffect, useCallback, useContext } from 'preact/hooks';

const I18nContext = createContext({ t: (key) => key, locale: 'en', setLocale: () => {} });

const SUPPORTED_LOCALES = ['en', 'es', 'ja'];

function detectLocale() {
  const stored = localStorage.getItem('locale');
  if (stored && SUPPORTED_LOCALES.includes(stored)) return stored;
  const browser = (navigator.language || '').split('-')[0];
  if (SUPPORTED_LOCALES.includes(browser)) return browser;
  return 'en';
}

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(detectLocale);
  const [messages, setMessages] = useState({});

  useEffect(() => {
    let cancelled = false;
    import(`./locales/${locale}.json`)
      .then((mod) => { if (!cancelled) setMessages(mod.default || mod); })
      .catch(() => {
        if (locale !== 'en') {
          import('./locales/en.json').then((mod) => { if (!cancelled) setMessages(mod.default || mod); });
        }
      });
    return () => { cancelled = true; };
  }, [locale]);

  const setLocale = useCallback((l) => {
    if (SUPPORTED_LOCALES.includes(l)) {
      localStorage.setItem('locale', l);
      setLocaleState(l);
    }
  }, []);

  const t = useCallback((key, params = {}) => {
    let msg = messages[key] || key;
    Object.entries(params).forEach(([k, v]) => { msg = msg.replace(`{${k}}`, v); });
    return msg;
  }, [messages]);

  return (
    <I18nContext.Provider value={{ t, locale, setLocale }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
