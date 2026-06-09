import { createContext } from 'preact';
import { useState, useEffect, useContext, useCallback } from 'preact/hooks';
import { fetchAgents } from './api.js';
import { useI18n } from './i18n-context.jsx';

const AgentContext = createContext({ agents: {}, loading: true, error: null });

export function AgentProvider({ children }) {
  const [agents, setAgents] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let retries = 0;

    function load() {
      fetchAgents()
        .then((data) => {
          if (cancelled) return;
          const map = {};
          (data.agents || []).forEach((a) => {
            // Normalize finding_schema from JSON string to object so
            // consumers (FindingCard, admin page) don't need to handle
            // both formats.
            if (typeof a.finding_schema === 'string') {
              try { a.finding_schema = JSON.parse(a.finding_schema); } catch { /* leave as-is */ }
            }
            map[a.agent_type] = a;
          });
          setAgents(map);
          setLoading(false);
        })
        .catch((err) => {
          if (cancelled) return;
          if (retries < 2) {
            retries++;
            setTimeout(load, 2000 * retries);
          } else {
            setError(err.message || 'Failed to load agent registry');
            setLoading(false);
          }
        });
    }
    load();
    return () => { cancelled = true; };
  }, []);

  return (
    <AgentContext.Provider value={{ agents, loading, error }}>
      {children}
    </AgentContext.Provider>
  );
}

export function useAgents() {
  return useContext(AgentContext);
}

/** Resolve a display label for an agent: i18n key → registry display_name → capitalized key. */
export function useAgentLabel() {
  const { agents } = useAgents();
  const { t } = useI18n();
  return useCallback((key) => {
    const i18nKey = `agent.${key}.name`;
    const translated = t(i18nKey);
    if (translated !== i18nKey) return translated;
    return agents[key]?.display_name || key.charAt(0).toUpperCase() + key.slice(1);
  }, [agents, t]);
}
