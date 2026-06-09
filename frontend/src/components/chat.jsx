import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import { useWs } from '../ws-context.jsx';
import { useAgents, useAgentLabel } from '../agent-context.jsx';
import { useI18n } from '../i18n-context.jsx';
import { renderMarkdown } from '../markdown.js';
import { ChatSessionList } from './chat-session-list.jsx';
import { TokenBudgetRing } from './token-budget-ring.jsx';

/** Clean JSON escape sequences from agent text */
function cleanText(text) {
  if (!text) return '';
  let clean = text;
  if (clean.startsWith('"') && clean.endsWith('"')) {
    clean = clean.slice(1, -1);
  }
  return clean.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
}

/** Markdown render cache for completed messages */
const htmlCache = new WeakMap();

/** Get rendered HTML for a message, using cache for completed ones */
function getMessageHtml(msg) {
  if (!msg._streaming) {
    let html = htmlCache.get(msg);
    if (!html) {
      html = renderMarkdown(cleanText(msg.content), 'chat');
      htmlCache.set(msg, html);
    }
    return html;
  }
  return renderMarkdown(cleanText(msg.content), 'chat');
}

export function Chat({ projectId, agent }) {
  // Message histories keyed by "agent:sessionId"
  const [histories, setHistories] = useState({});
  // Sessions keyed by agent
  const [sessions, setSessions] = useState({});
  const [sessionsLoaded, setSessionsLoaded] = useState({});
  const [currentSessionId, setCurrentSessionId] = useState(null);

  const [input, setInput] = useState('');
  const [status, setStatus] = useState('disconnected');
  const [streaming, setStreaming] = useState(false);
  const [hasFindings, setHasFindings] = useState(null);
  const [hasDocumentSearch, setHasDocumentSearch] = useState(false);
  const [hasStandardsLookup, setHasStandardsLookup] = useState(false);
  const [warning, setWarning] = useState(null);
  // Usage keyed by "agent:sessionId" — survives tab switches within the page
  const [usageBySession, setUsageBySession] = useState({});
  const ws = useWs();
  const { agents } = useAgents();
  const { t } = useI18n();
  const messagesRef = useRef(null);
  const streamBuf = useRef(null);
  const streamTimer = useRef(null);
  // Track pending first-message sends that need a session created first
  const pendingMessage = useRef(null);

  const INITIAL_STREAM_TIMEOUT = 60_000;
  const INTER_CHUNK_TIMEOUT = 20_000;

  // Composite key for histories
  const historyKey = currentSessionId ? `${agent}:${currentSessionId}` : null;

  // Subscribe to WebSocket status
  useEffect(() => {
    if (!ws) return;
    return ws.onStatus(setStatus);
  }, [ws]);

  // Reset session selection when agent tab changes. Without this,
  // currentSessionId retains the previous agent's session ID, causing
  // messages to be stored against a session that doesn't exist for the
  // new agent (orphaned messages + "Chat session not found" errors).
  useEffect(() => {
    if (!sessionsLoaded[agent]) {
      // Agent not loaded yet — clear selection, listChatSessions will set it
      setCurrentSessionId(null);
    } else {
      // Agent already loaded — select its most recent session (or null)
      const agentSessions = sessions[agent] || [];
      setCurrentSessionId(
        agentSessions.length > 0
          ? agentSessions[agentSessions.length - 1].session_id
          : null
      );
    }
  }, [agent]);

  // Load sessions when agent changes (or on first mount)
  useEffect(() => {
    if (!ws || status !== 'connected' || sessionsLoaded[agent]) return;
    ws.send({ action: 'listChatSessions', projectId, agent });
  }, [ws, status, agent, projectId, sessionsLoaded]);

  const addMsg = useCallback(
    (key, role, content) => {
      setHistories((prev) => ({
        ...prev,
        [key]: [...(prev[key] || []), { role, content, agent, time: new Date() }],
      }));
    },
    [agent]
  );

  const finishStream = useCallback((timedOut = false) => {
    clearTimeout(streamTimer.current);
    streamTimer.current = null;
    if (streamBuf.current) {
      const key = streamBuf.current.historyKey;
      setHistories((prev) => {
        const msgs = (prev[key] || []).map((m) =>
          m._streaming ? { ...m, _streaming: false } : m
        );
        return { ...prev, [key]: msgs };
      });
      if (timedOut && historyKey) {
        addMsg(key, 'system', t('chat.streamTimeout'));
      }
    }
    streamBuf.current = null;
    setStreaming(false);
  }, [addMsg, t, historyKey]);

  const handleMessage = useCallback((data) => {
    switch (data.type) {
      case 'chunk': {
        clearTimeout(streamTimer.current);
        if (!streamBuf.current) {
          streamBuf.current = {
            agent: data.agent || agent,
            historyKey: historyKey,
            text: '',
          };
        }
        streamTimer.current = setTimeout(() => finishStream(true), INTER_CHUNK_TIMEOUT);

        streamBuf.current.text += data.content;
        const key = streamBuf.current.historyKey;
        setHistories((prev) => {
          const msgs = [...(prev[key] || [])];
          const last = msgs[msgs.length - 1];
          if (last && last.role === 'assistant' && last._streaming) {
            msgs[msgs.length - 1] = { ...last, content: streamBuf.current.text };
          } else {
            msgs.push({
              role: 'assistant', content: streamBuf.current.text,
              agent: streamBuf.current.agent, time: new Date(), _streaming: true,
            });
          }
          return { ...prev, [key]: msgs };
        });
        break;
      }
      case 'complete':
        setWarning(null);
        finishStream(false);
        break;
      case 'error':
        clearTimeout(streamTimer.current);
        streamTimer.current = null;
        if (historyKey) addMsg(historyKey, 'system', `Error: ${data.error}`);
        streamBuf.current = null;
        setStreaming(false);
        break;
      case 'chat_capabilities':
        setHasFindings(data.has_findings);
        setHasDocumentSearch(data.has_document_search || false);
        setHasStandardsLookup(data.has_standards_lookup || false);
        break;
      case 'chat_warning':
        setWarning(data.warning);
        break;
      case 'usage':
        if (historyKey) {
          setUsageBySession((prev) => ({ ...prev, [historyKey]: data }));
        }
        break;

      // ── Session CRUD responses ──
      case 'chat_sessions':
        setSessions((prev) => ({ ...prev, [data.agent]: data.sessions }));
        setSessionsLoaded((prev) => ({ ...prev, [data.agent]: true }));
        // Auto-select most recent session (last in the list, sorted oldest-first)
        if (data.sessions.length > 0 && data.agent === agent) {
          setCurrentSessionId(data.sessions[data.sessions.length - 1].session_id);
        }
        break;

      case 'chat_session_created': {
        setSessions((prev) => ({
          ...prev,
          [data.agent]: [...(prev[data.agent] || []), data.session],
        }));
        if (data.agent === agent) {
          setCurrentSessionId(data.session.session_id);
        }
        // If there's a pending message waiting for session creation, send it now
        if (pendingMessage.current && data.agent === agent) {
          const text = pendingMessage.current;
          pendingMessage.current = null;
          const newKey = `${agent}:${data.session.session_id}`;
          setHistories((prev) => ({
            ...prev,
            [newKey]: [{ role: 'user', content: text, agent, time: new Date() }],
          }));
          ws.send({
            action: 'sendMessage', projectId, agent,
            sessionId: data.session.session_id, message: text,
          });
          setStreaming(true);
          clearTimeout(streamTimer.current);
          streamBuf.current = { agent, historyKey: newKey, text: '' };
          streamTimer.current = setTimeout(() => finishStream(true), INITIAL_STREAM_TIMEOUT);
        }
        break;
      }

      case 'chat_session_deleted':
        setSessions((prev) => ({
          ...prev,
          [data.agent]: (prev[data.agent] || []).filter(
            (s) => s.session_id !== data.session_id
          ),
        }));
        // If deleted session was active, select next available (rightmost)
        if (data.agent === agent && currentSessionId === data.session_id) {
          const remaining = (sessions[agent] || []).filter(
            (s) => s.session_id !== data.session_id
          );
          setCurrentSessionId(remaining.length > 0 ? remaining[remaining.length - 1].session_id : null);
        }
        break;

      case 'chat_history':
        if (data.agent === agent) {
          const key = `${data.agent}:${data.session_id}`;
          setHistories((prev) => ({
            ...prev,
            [key]: data.messages.map((m) => ({
              role: m.role, content: m.content, agent: data.agent,
              time: new Date(m.timestamp),
            })),
          }));
        }
        break;

      case 'chat_session_updated':
        // Server pushed an updated title (after first message)
        setSessions((prev) => ({
          ...prev,
          [data.agent]: (prev[data.agent] || []).map((s) =>
            s.session_id === data.session_id
              ? { ...s, title: data.title }
              : s
          ),
        }));
        break;
    }
  }, [agent, addMsg, finishStream, historyKey, projectId, ws, sessions, currentSessionId]);

  // Subscribe to incoming messages
  useEffect(() => {
    if (!ws) return;
    return ws.subscribe(handleMessage);
  }, [ws, handleMessage]);

  // Load messages when selecting a session that hasn't been loaded yet
  useEffect(() => {
    if (!ws || !currentSessionId || status !== 'connected') return;
    const key = `${agent}:${currentSessionId}`;
    if (histories[key] !== undefined) return; // already loaded or in-progress
    ws.send({ action: 'loadChatHistory', projectId, agent, sessionId: currentSessionId });
  }, [ws, agent, currentSessionId, projectId, status, histories]);

  const messages = historyKey ? (histories[historyKey] || []) : [];
  const agentMeta = agents[agent];
  const getAgentLabel = useAgentLabel();
  const agentLabel = getAgentLabel(agent);
  const agentIcon = agentMeta?.icon || '🤖';
  const agentSessions = sessions[agent] || [];

  // Auto-scroll: always scroll to bottom when new messages arrive, during
  // streaming, or when switching sessions. Uses a ref to detect content
  // growth and only force-scrolls when the user is near the bottom.
  const prevScrollHeight = useRef(0);
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    const contentGrew = el.scrollHeight > prevScrollHeight.current;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (contentGrew && nearBottom) el.scrollTop = el.scrollHeight;
    prevScrollHeight.current = el.scrollHeight;
  });

  // Force scroll to bottom on session switch
  useEffect(() => {
    const el = messagesRef.current;
    if (el) {
      // Defer to next frame so DOM has rendered the new messages
      requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
    }
  }, [currentSessionId]);

  function send() {
    const text = input.trim();
    if (!text || !ws || status !== 'connected' || streaming) return;

    // If no sessions exist, auto-create one then send the message
    if (!currentSessionId) {
      pendingMessage.current = text;
      ws.send({ action: 'createChatSession', projectId, agent });
      setInput('');
      return;
    }

    addMsg(historyKey, 'user', text);
    ws.send({
      action: 'sendMessage', projectId, agent,
      sessionId: currentSessionId, message: text,
    });
    setInput('');
    setStreaming(true);
    clearTimeout(streamTimer.current);
    streamTimer.current = setTimeout(() => finishStream(true), INITIAL_STREAM_TIMEOUT);
  }

  function handleCreateSession() {
    if (!ws || status !== 'connected') return;
    ws.send({ action: 'createChatSession', projectId, agent });
  }

  function handleDeleteSession(sessionId) {
    if (!ws || status !== 'connected') return;
    ws.send({ action: 'deleteChatSession', projectId, agent, sessionId });
  }

  return (
    <div class="chat-panel">
      <div class="chat-panel-body">
        <ChatSessionList
          sessions={agentSessions}
          currentSessionId={currentSessionId}
          onSelect={setCurrentSessionId}
          onCreate={handleCreateSession}
          onDelete={handleDeleteSession}
          disabled={streaming}
        />

        <div class="chat-messages custom-scroll" ref={messagesRef} role="log" aria-live="polite">
          {messages.length === 0 && (
            <div class="message system">
              <div class="message-content">
                {!currentSessionId
                  ? t('chat.emptyState', { agent: agentLabel })
                  : hasFindings === false
                    ? t('chat.emptyStateNoFindings', { agent: agentLabel })
                    : t('chat.emptyState', { agent: agentLabel })}
              </div>
            </div>
          )}
          {warning && (
            <div class="message system chat-warning">
              <div class="message-content">
                ⚠ {warning}
                <button class="chat-warning-dismiss" onClick={() => setWarning(null)} aria-label={t('common.close')}>✕</button>
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} class={`message ${m.role}`}>
              <div class="message-content" dangerouslySetInnerHTML={{ __html: getMessageHtml(m) }} />
            </div>
          ))}
          {streaming && !streamBuf.current?.text && (
            <div class="thinking-indicator">
              <span>{agentIcon}</span>
              <span>{t('chat.thinking', { agent: agentLabel })}</span>
              <div class="thinking-dots"><span /><span /><span /></div>
            </div>
          )}
        </div>

        {status !== 'connected' && (
          <div class={`connection-status ${status}`}>
            <span class="status-dot" />
            <span class="status-text">
              {status === 'connecting' ? t('common.connecting') : t('common.disconnected')}
            </span>
          </div>
        )}

        <div class="chat-input-container">
          <div class="chat-input-row">
            <textarea
              value={input}
              onInput={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
              }}
              placeholder={t('chat.placeholder', { agent: agentLabel.toLowerCase() })}
              rows={2}
            />
            <button
              class="chat-send-btn"
              disabled={status !== 'connected' || streaming}
              onClick={send}
              aria-label="Send message"
            >
              <span class="send-icon">➤</span>
            </button>
          </div>
          <TokenBudgetRing usage={historyKey ? usageBySession[historyKey] : null} modelId={historyKey ? usageBySession[historyKey]?.model_id : null} />
        </div>
      </div>
    </div>
  );
}
