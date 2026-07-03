/**
 * Horizontal tab bar for chat sessions. Each session is a tab with a
 * close (×) button. A "+" button creates new sessions.
 *
 * @param {Object} props
 * @param {Array} props.sessions - Session metadata objects.
 * @param {string|null} props.currentSessionId - Currently selected session.
 * @param {(id: string) => void} props.onSelect - Called when a tab is clicked.
 * @param {() => void} props.onCreate - Called when "+" is clicked.
 * @param {(id: string) => void} props.onDelete - Called when a tab is closed.
 * @param {boolean} props.disabled - Disable interactions (e.g. while streaming).
 */
export function ChatSessionList({
  sessions,
  currentSessionId,
  onSelect,
  onCreate,
  onDelete,
  disabled,
}) {
  function handleClose(e, sessionId) {
    e.stopPropagation();
    e.preventDefault();
    onDelete(sessionId);
  }

  if (sessions.length === 0) return null;

  return (
    <div class="chat-tabs" role="tablist" aria-label="Chat sessions">
      <div class="chat-tabs-scroll">
        {sessions.map((s) => (
          <div
            key={s.session_id}
            role="tab"
            tabIndex={0}
            aria-selected={s.session_id === currentSessionId}
            class={`chat-tab ${s.session_id === currentSessionId ? 'active' : ''}`}
            onClick={() => !disabled && onSelect(s.session_id)}
            onKeyDown={(e) => { if (e.key === 'Enter') onSelect(s.session_id); }}
          >
            <span class="chat-tab-title" title={s.title}>{s.title}</span>
            <button
              class="chat-tab-close"
              onClick={(e) => handleClose(e, s.session_id)}
              disabled={disabled}
              aria-label={`Close "${s.title}"`}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <button
        class="chat-tab-new"
        onClick={onCreate}
        disabled={disabled}
        aria-label="New chat"
        title="New chat"
      >
        +
      </button>
    </div>
  );
}
