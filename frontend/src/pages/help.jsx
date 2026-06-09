import { useState, useEffect, useMemo } from 'preact/hooks';
import { useAuth } from '../auth.jsx';
import { useI18n } from '../i18n-context.jsx';
import { renderMarkdown } from '../markdown.js';

// Static imports of markdown docs — bundled at build time
import overview from '../docs/overview.md?raw';
import gettingStarted from '../docs/getting-started.md?raw';
import understandingReviews from '../docs/understanding-reviews.md?raw';
import readingFindings from '../docs/reading-findings.md?raw';
import usingChat from '../docs/using-chat.md?raw';
import analytics from '../docs/analytics.md?raw';
import contexts from '../docs/contexts.md?raw';
import architecture from '../docs/architecture.md?raw';
import contact from '../docs/contact.md?raw';
import adminBenchmarks from '../docs/admin-benchmarks.md?raw';
import adminRegistry from '../docs/admin-registry.md?raw';
import adminNewAgent from '../docs/admin-new-agent.md?raw';
import adminUsers from '../docs/admin-users.md?raw';
import apiReference from '../docs/api-reference.md?raw';

const USER_TOPICS = [
  { id: 'overview', titleKey: 'help.topic.overview', content: overview },
  { id: 'getting-started', titleKey: 'help.topic.gettingStarted', content: gettingStarted },
  { id: 'understanding-reviews', titleKey: 'help.topic.understandingReviews', content: understandingReviews },
  { id: 'reading-findings', titleKey: 'help.topic.readingFindings', content: readingFindings },
  { id: 'using-chat', titleKey: 'help.topic.usingChat', content: usingChat },
  { id: 'analytics', titleKey: 'help.topic.analytics', content: analytics },
  { id: 'contexts', titleKey: 'help.topic.contexts', content: contexts },
  { id: 'architecture', titleKey: 'help.topic.architecture', content: architecture },
  { id: 'contact', titleKey: 'help.topic.contact', content: contact },
];

const ADMIN_TOPICS = [
  { id: 'admin-benchmarks', titleKey: 'help.topic.adminBenchmarks', content: adminBenchmarks },
  { id: 'admin-registry', titleKey: 'help.topic.adminRegistry', content: adminRegistry },
  { id: 'admin-new-agent', titleKey: 'help.topic.adminNewAgent', content: adminNewAgent },
  { id: 'admin-users', titleKey: 'help.topic.adminUsers', content: adminUsers },
  { id: 'api-reference', titleKey: 'help.topic.apiReference', content: apiReference },
];

export function HelpPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const isAdmin = user?.groups?.includes('admins');
  const [activeId, setActiveId] = useState('overview');

  // Handle hash-based deep linking
  useEffect(() => {
    const hash = window.location.hash.replace('#', '');
    if (hash) {
      const allTopics = [...USER_TOPICS, ...ADMIN_TOPICS];
      if (allTopics.some((t) => t.id === hash)) setActiveId(hash);
    }
  }, []);

  function selectTopic(id) {
    setActiveId(id);
    window.history.replaceState(null, '', `/help#${id}`);
  }

  const allTopics = useMemo(() => {
    return isAdmin ? [...USER_TOPICS, ...ADMIN_TOPICS] : USER_TOPICS;
  }, [isAdmin]);

  const activeTopic = allTopics.find((t) => t.id === activeId) || allTopics[0];
  const rendered = useMemo(() => renderMarkdown(activeTopic.content), [activeTopic]);

  return (
    <div class="help-layout">
      <aside class="help-sidebar">
        <div class="help-sidebar-section">
          <h4 class="help-sidebar-heading">{t('help.section.userGuide')}</h4>
          {USER_TOPICS.map((topic) => (
            <button
              key={topic.id}
              class={`help-sidebar-link ${activeId === topic.id ? 'active' : ''}`}
              onClick={() => selectTopic(topic.id)}
            >
              {t(topic.titleKey)}
            </button>
          ))}
        </div>
        {isAdmin && (
          <div class="help-sidebar-section help-sidebar-section--admin">
            <h4 class="help-sidebar-heading">{t('help.section.adminGuide')}</h4>
            {ADMIN_TOPICS.map((topic) => (
              <button
                key={topic.id}
                class={`help-sidebar-link ${activeId === topic.id ? 'active' : ''}`}
                onClick={() => selectTopic(topic.id)}
              >
                {t(topic.titleKey)}
              </button>
            ))}
          </div>
        )}
      </aside>
      <article class="help-content" dangerouslySetInnerHTML={{ __html: rendered }} />
    </div>
  );
}
