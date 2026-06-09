import { useState, useCallback, useEffect } from 'preact/hooks';
import { useAgents } from '../agent-context.jsx';
import { useI18n } from '../i18n-context.jsx';

const DEPTHS = ['quick', 'standard', 'thorough'];

export function PlanCustomizePanel({ plan, originalPlan, onSave, onCancel, onChange }) {
  const [editPlan, setEditPlan] = useState(() => JSON.parse(JSON.stringify(plan)));
  const { agents } = useAgents();
  const { t } = useI18n();

  // Build agent config from registry for display
  const agentCfg = (type) => {
    const a = agents[type];
    return a ? { label: a.display_name, icon: a.icon, color: a.color } : { label: type, icon: '🔍', color: '#888' };
  };

  useEffect(() => {
    if (onChange) onChange(editPlan);
  }, [editPlan]);

  const handleReset = useCallback(() => {
    if (originalPlan) setEditPlan(JSON.parse(JSON.stringify(originalPlan)));
  }, [originalPlan]);

  // --- Group-level mutations ---
  const removeGroup = useCallback((gi) => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      next.groups.splice(gi, 1);
      return next;
    });
  }, []);

  // --- Agent-level mutations ---
  const updateAgent = useCallback((gi, ai, patch) => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      Object.assign(next.groups[gi].agents[ai], patch);
      return next;
    });
  }, []);

  const removeAgent = useCallback((gi, ai) => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      next.groups[gi].agents.splice(ai, 1);
      next.groups = next.groups.filter(g => g.agents.length > 0);
      return next;
    });
  }, []);

  const moveAgent = useCallback((fromGi, ai, toGi) => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      const [agent] = next.groups[fromGi].agents.splice(ai, 1);
      next.groups[toGi].agents.push(agent);
      next.groups = next.groups.filter(g => g.agents.length > 0);
      return next;
    });
  }, []);

  const addFocusArea = useCallback((gi, ai, area) => {
    if (!area.trim()) return;
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      const fa = next.groups[gi].agents[ai].focus_areas || [];
      if (!fa.includes(area.trim())) fa.push(area.trim());
      next.groups[gi].agents[ai].focus_areas = fa;
      return next;
    });
  }, []);

  const removeFocusArea = useCallback((gi, ai, area) => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      next.groups[gi].agents[ai].focus_areas = (next.groups[gi].agents[ai].focus_areas || []).filter(a => a !== area);
      return next;
    });
  }, []);

  const addAgent = useCallback((agentType) => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      next.groups[next.groups.length - 1].agents.push({
        agent_type: agentType, depth: 'standard', focus_areas: [], prompt_addendum: '',
      });
      return next;
    });
  }, []);

  const addGroup = useCallback(() => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      next.groups.push({
        group_id: `group_${next.groups.length}`, label: `Group ${next.groups.length + 1}`,
        execution: 'sequential', agents: [],
      });
      return next;
    });
  }, []);

  // --- Derived data ---
  const usedAgents = new Set();
  editPlan.groups.forEach(g => g.agents.forEach(a => usedAgents.add(a.agent_type)));
  const availableToAdd = Object.keys(agents).filter(a => agents[a]?.has_review_agent && !usedAgents.has(a));
  const totalAgents = editPlan.groups.reduce((s, g) => s + g.agents.length, 0);

  // --- Preset: Sequential Chain ---
  // Splits all agents into separate single-agent groups (sequential ordering without depends_on)
  const applySequentialChain = useCallback(() => {
    setEditPlan(p => {
      const next = JSON.parse(JSON.stringify(p));
      const allAgents = [];
      next.groups.forEach(g => g.agents.forEach(a => allAgents.push(a)));
      next.groups = allAgents.map((agent, i) => ({
        group_id: `chain_${i}`,
        label: agentCfg(agent.agent_type).label || `Step ${i + 1}`,
        execution: 'sequential',
        agents: [agent],
      }));
      return next;
    });
  }, []);

  return (
    <div class="cp-panel">
      <div class="cp-header">
        <span>{t('plan.customize')}</span>
        <button class="cp-close" onClick={onCancel} aria-label="Close customize panel">✕</button>
      </div>

      <div class="cp-body custom-scroll">
        {editPlan.groups.map((group, gi) => (
          <div key={group.group_id + gi} class="cp-group">
            <div class="cp-group-header">
              <span class="cp-group-label">{group.label}</span>
              <div class="cp-group-controls">
                {editPlan.groups.length > 1 && (
                  <button class="cp-remove" onClick={() => removeGroup(gi)} aria-label={t('plan.removeGroup')} title={t('plan.removeGroup')}>✕</button>
                )}
              </div>
            </div>

            {group.agents.map((agent, ai) => {
              const cfg = agentCfg(agent.agent_type);
              return (
                <AgentEditor
                  key={`${gi}-${agent.agent_type}`}
                  agent={agent} cfg={cfg}
                  groupIdx={gi} agentIdx={ai}
                  canRemove={totalAgents > 1}
                  canMoveToGroup={editPlan.groups.length > 1}
                  groupCount={editPlan.groups.length}
                  currentGroupIdx={gi}
                  onUpdate={updateAgent} onRemove={removeAgent}
                  onAddFocus={addFocusArea} onRemoveFocus={removeFocusArea}
                  onMoveToGroup={moveAgent}
                  agentCfg={agentCfg}
                />
              );
            })}

            {group.agents.length === 0 && (
              <div class="cp-empty-group">{t('plan.emptyGroup')}</div>
            )}
          </div>
        ))}
      </div>

      <div class="cp-actions-row">
        {availableToAdd.length > 0 && <AddAgentDropdown agents={availableToAdd} onAdd={addAgent} agentCfg={agentCfg} />}
        <button class="btn btn-secondary btn-small" onClick={addGroup}>{t('plan.addGroup')}</button>
        <button class="btn btn-secondary btn-small" onClick={applySequentialChain} title="Split into separate groups with cascading dependencies">{t('plan.sequentialChain')}</button>
        <div style="flex:1" />
        <button class="btn btn-secondary btn-small" onClick={handleReset}>{t('plan.resetToAI')}</button>
        <button class="btn btn-primary btn-small" onClick={() => onSave(editPlan)} disabled={totalAgents === 0}>
          {t('plan.save')}
        </button>
      </div>
    </div>
  );
}

// --- Agent Editor ---
function AgentEditor({ agent, cfg, groupIdx, agentIdx, canRemove,
  canMoveToGroup, groupCount, currentGroupIdx,
  onUpdate, onRemove, onAddFocus, onRemoveFocus, onMoveToGroup, agentCfg }) {
  const [focusInput, setFocusInput] = useState('');
  const [showAddendum, setShowAddendum] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const { t } = useI18n();

  const handleFocusKey = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      onAddFocus(groupIdx, agentIdx, focusInput);
      setFocusInput('');
    }
  };

  return (
    <div class="cp-agent" style={{ '--agent-color': cfg.color }}>
      <div class="cp-agent-header">
        <span class="cp-agent-name">{cfg.icon} {cfg.label}</span>
        <div class="cp-agent-actions">
          {canMoveToGroup && groupCount > 1 && (
            <div style="position:relative;display:inline-block">
              <button class="cp-move-btn" onClick={() => setShowMove(!showMove)} title={t('plan.moveToGroup')}>⇄</button>
              {showMove && (
                <div class="cp-dropdown" style="right:0;left:auto">
                  {Array.from({ length: groupCount }, (_, i) => i).filter(i => i !== currentGroupIdx).map(i => (
                    <button key={i} class="cp-dropdown-item" onClick={() => { onMoveToGroup(groupIdx, agentIdx, i); setShowMove(false); }}>
                      Group {i + 1}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {canRemove && <button class="cp-remove" onClick={() => onRemove(groupIdx, agentIdx)} aria-label={`Remove ${cfg.label}`}>✕</button>}
        </div>
      </div>

      {/* Depth */}
      <div class="cp-field">
        <span class="cp-field-label">{t('plan.depth')}</span>
        <div class="cp-depth-group" role="radiogroup" aria-label="Review depth">
          {DEPTHS.map(d => (
            <button key={d}
              class={`cp-depth-btn ${agent.depth === d ? 'cp-depth-btn--active' : ''}`}
              onClick={() => onUpdate(groupIdx, agentIdx, { depth: d })}
              role="radio" aria-checked={agent.depth === d}
            >{t(`plan.depth.${d}`)}</button>
          ))}
        </div>
      </div>

      {/* Focus Areas */}
      <div class="cp-field">
        <span class="cp-field-label">{t('plan.focusAreas')}</span>
        <div class="cp-tags">
          {(agent.focus_areas || []).map(fa => (
            <span key={fa} class="cp-tag">
              {fa}
              <button class="cp-tag-x" onClick={() => onRemoveFocus(groupIdx, agentIdx, fa)} aria-label={`Remove ${fa}`}>✕</button>
            </span>
          ))}
          <input class="cp-tag-input" type="text" placeholder={t('plan.focusAreaPlaceholder')} value={focusInput}
            onInput={e => setFocusInput(e.target.value)} onKeyDown={handleFocusKey} aria-label="Add focus area" />
        </div>
      </div>

      {/* Prompt Addendum */}
      <div class="cp-field">
        <button class="cp-addendum-toggle" onClick={() => setShowAddendum(!showAddendum)}>
          {showAddendum ? '▾' : '▸'} {t('plan.promptAddendum')}
        </button>
        {showAddendum && (
          <textarea class="cp-addendum-textarea" value={agent.prompt_addendum || ''}
            onInput={e => onUpdate(groupIdx, agentIdx, { prompt_addendum: e.target.value })}
            rows={3} placeholder={t('plan.promptAddendumPlaceholder')} aria-label="Prompt addendum" />
        )}
      </div>

      {/* Quality Judge */}
      <div class="cp-field cp-judge-section">
        <div class="cp-judge-header">
          <span class="cp-field-label">⚖️ {t('plan.judge')}</span>
          <label class="cp-toggle" aria-label={t('plan.judge')}>
            <input type="checkbox" checked={agent.judge?.enabled || false}
              onChange={e => onUpdate(groupIdx, agentIdx, { judge: { ...(agent.judge || {}), enabled: e.target.checked } })} />
            <span class="cp-toggle-slider" />
          </label>
          {agent.judge?.enabled && !agent.coach_guidance && (
            <span class="cp-judge-warning" title={t('plan.judgeNoGuidance')}>⚠️ {t('plan.judgeNoGuidanceShort')}</span>
          )}
          {agent.judge?.enabled && (
            <div class="cp-judge-controls">
              <div class="cp-judge-row">
                <span class="cp-judge-label">{t('plan.judgeMaxIter')}</span>
                <span class="cp-judge-bound">1</span>
                <input type="range" min="1" max="5" step="1" value={agent.judge?.max_iterations || 3}
                  onInput={e => onUpdate(groupIdx, agentIdx, { judge: { ...agent.judge, max_iterations: parseInt(e.target.value) } })}
                  class="cp-judge-range" aria-label="Max iterations" />
                <span class="cp-judge-value">{agent.judge?.max_iterations || 3}</span>
              </div>
              <div class="cp-judge-row">
                <span class="cp-judge-label">{t('plan.judgeThreshold')}</span>
                <span class="cp-judge-bound">.50</span>
                <input type="range" min="0.5" max="1.0" step="0.05" value={agent.judge?.quality_threshold || 0.8}
                  onInput={e => onUpdate(groupIdx, agentIdx, { judge: { ...agent.judge, quality_threshold: parseFloat(e.target.value) } })}
                  class="cp-judge-range" aria-label="Quality threshold" />
                <span class="cp-judge-value">{(agent.judge?.quality_threshold || 0.8).toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Add Agent Dropdown ---
function AddAgentDropdown({ agents, onAdd, agentCfg }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  return (
    <div class="cp-add-agent" style="position:relative">
      <button class="btn btn-secondary btn-small" onClick={() => setOpen(!open)}>+ {t('plan.addAgent')}</button>
      {open && (
        <div class="cp-dropdown">
          {agents.map(a => {
            const cfg = agentCfg(a);
            return (
              <button key={a} class="cp-dropdown-item" onClick={() => { onAdd(a); setOpen(false); }}>
                {cfg.icon} {cfg.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
