import { useState } from 'preact/hooks';
import { route } from 'preact-router';
import { useAuth } from '../auth.jsx';

const WELCOME_KEY = 'app_welcomed';

function shouldShowWelcome() {
  return !localStorage.getItem(WELCOME_KEY);
}

function dismissWelcome() {
  localStorage.setItem(WELCOME_KEY, '1');
}

/**
 * Welcome modal shown on first login. Content varies by user role.
 * Uses localStorage to track dismissal — if cleared, shows again (acceptable for demo).
 */
export function WelcomeModal() {
  const { user } = useAuth();
  const [visible, setVisible] = useState(shouldShowWelcome);

  if (!visible) return null;

  const isViewer = !user.groups.includes('users') && !user.groups.includes('admins');
  const displayRole = user.groups.includes('admins') ? 'admin' : user.groups.includes('users') ? 'user' : 'viewer';

  function handleDismiss() {
    dismissWelcome();
    setVisible(false);
  }

  function handleLearnMore() {
    dismissWelcome();
    setVisible(false);
    route('/help#overview');
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div class="modal-overlay" onClick={(e) => e.target === e.currentTarget && handleDismiss()} onKeyDown={(e) => e.key === 'Escape' && handleDismiss()} role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div class="welcome-modal">
        <h2 id="welcome-title">Welcome to Assess Workbench</h2>
        <p>
          Assess Workbench reviews your key documents with a team of specialist
          AI agents — architecture, risk, security, compliance, and more — and gives
          you traceable findings you can act on and defend.
        </p>
        {isViewer ? (
          <p class="welcome-access-note">
            You have <strong>viewer</strong> access — you can browse projects and chat with agents.
            Need full access? Ask an admin to promote your account.
          </p>
        ) : (
          <p class="welcome-access-note">
            You have <strong>{displayRole}</strong> access. You&apos;re all set to start.
          </p>
        )}
        <div class="welcome-modal-actions">
          <button class="btn btn-secondary" onClick={handleLearnMore}>
            Learn more
          </button>
          <button class="btn btn-primary" onClick={handleDismiss}>
            Get started
          </button>
        </div>
      </div>
    </div>
  );
}
