import { useState, useEffect, useRef } from 'preact/hooks';
import { useAuth } from '../auth.jsx';
import { useI18n } from '../i18n-context.jsx';
import { useTheme } from '../use-theme.js';
import { HealthBanner } from './health-banner.jsx';

function NavLink({ href, children }) {
  const isCurrent = window.location.pathname === href
    || (href !== '/' && window.location.pathname.startsWith(href));
  return (
    <a href={href} class={`nav-link${isCurrent ? ' active' : ''}`} aria-current={isCurrent ? 'page' : undefined}>
      {children}
    </a>
  );
}

function AdminDropdown({ t }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const isAdminPage = window.location.pathname.startsWith('/admin');

  useEffect(() => {
    if (!open) return;
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div class="nav-dropdown" ref={ref}>
      <button
        class={`nav-link nav-dropdown-trigger${isAdminPage ? ' active' : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
      >
        {t('nav.admin')} <span class="nav-dropdown-arrow">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div class="dropdown-menu nav-dropdown-menu">
          <a href="/admin" class="dropdown-item" onClick={() => setOpen(false)}>
            {t('nav.adminAgents')}
          </a>
          <a href="/admin/standards" class="dropdown-item" onClick={() => setOpen(false)}>
            {t('nav.adminStandards')}
          </a>
          <a href="/admin/guardrail-events" class="dropdown-item" onClick={() => setOpen(false)}>
            {t('nav.adminGuardrails')}
          </a>
        </div>
      )}
    </div>
  );
}

export function Layout({ children }) {
  const { user, logout } = useAuth();
  const { locale, setLocale, t } = useI18n();
  const { theme, toggle: toggleTheme } = useTheme();
  // Admin nav (the Admin dropdown) is visible to admins AND viewers.
  // Viewer is a full-read role: demo stakeholders see every admin view but the
  // controls within are disabled (user.readOnly). The "users" role does NOT
  // see these views. Mirrors the backend's can_read_admin_views predicate.
  const canSeeAdminViews = user?.groups?.includes('admins') || user?.readOnly;

  return (
    <div class="container">
      <header class="top-bar">
        <div class="top-bar-left">
          <a href="/" class="top-bar-brand">{t('nav.brand')}</a>
          <nav class="top-bar-nav">
            <NavLink href="/">{t('nav.projects')}</NavLink>
            <NavLink href="/contexts">{t('nav.contexts')}</NavLink>
            <NavLink href="/analytics">{t('nav.analytics')}</NavLink>
            <NavLink href="/demo">{t('nav.agentDemo')}</NavLink>
            <span class="nav-separator" />
            <NavLink href="/help">{t('nav.help')}</NavLink>
          </nav>
          {canSeeAdminViews && (
            <>
              <span class="nav-separator" />
              <nav class="top-bar-nav top-bar-nav--admin">
                <AdminDropdown t={t} />
              </nav>
            </>
          )}
        </div>
        {user && (
          <div class="auth-section">
            <select
              class="locale-switcher"
              value={locale}
              onChange={(e) => setLocale(e.target.value)}
              aria-label="Select language"
            >
              <option value="en">EN</option>
              <option value="es">ES</option>
              <option value="ja">JA</option>
            </select>
            <label class="theme-switch" title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
              <input
                type="checkbox"
                checked={theme === 'light'}
                onChange={toggleTheme}
                aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              />
              <span class="theme-switch-track">
                <span class="theme-switch-icon">☀️</span>
                <span class="theme-switch-icon">🌙</span>
              </span>
            </label>
            <span class="user-email">{user.email}</span>
            <button class="btn btn-secondary btn-small" onClick={logout}>
              {t('nav.signOut')}
            </button>
          </div>
        )}
      </header>
      <HealthBanner />
      <main>{children}</main>
    </div>
  );
}
