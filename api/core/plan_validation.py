"""Plan validation logic shared between plan_review Lambda and review_service."""
from typing import Dict, List, Set


VALID_DEPTHS = {'quick', 'standard', 'thorough'}


def validate_judge_config(judge):
    """Validate and sanitize judge coaching config.

    Args:
        judge: Raw judge config dict from planner or user input.

    Returns:
        Sanitized judge config with safe defaults. Returns plain Python
        numbers — Decimal conversion for DynamoDB happens at the write boundary.
    """
    if not judge or not isinstance(judge, dict):
        return {'enabled': False, 'max_iterations': 3, 'quality_threshold': 0.8}

    enabled = bool(judge.get('enabled', False))

    max_iter = judge.get('max_iterations', 3)
    if not isinstance(max_iter, (int, float)) or max_iter < 1:
        max_iter = 1
    elif max_iter > 5:
        max_iter = 5

    threshold = judge.get('quality_threshold', 0.8)
    if not isinstance(threshold, (int, float)) or threshold < 0.5:
        threshold = 0.5
    elif threshold > 1.0:
        threshold = 1.0

    return {
        'enabled': enabled,
        'max_iterations': int(max_iter),
        'quality_threshold': round(float(threshold), 2),
    }


def validate_plan(plan: Dict, available_agents: Set[str]) -> Dict:
    """Validate and sanitize a review plan.

    Constrains to known agents and valid values. Falls back to the
    standard parallel workflow if the plan produces nothing usable.

    Args:
        plan: Raw plan dict from planner or user override.
        available_agents: Set of valid agent type strings.

    Returns:
        Plan dict with validated groups.
    """
    validated_groups = []
    seen_agents = set()

    for group in plan.get('groups', []):
        validated_agents = []
        for agent in group.get('agents', []):
            agent_type = agent.get('agent_type', '')
            if agent_type not in available_agents or agent_type in seen_agents:
                continue
            seen_agents.add(agent_type)

            depth = agent.get('depth', 'standard')
            if depth not in VALID_DEPTHS:
                depth = 'standard'

            validated_agents.append({
                'agent_type': agent_type,
                'depth': depth,
                'focus_areas': agent.get('focus_areas', [])[:10],
                'prompt_addendum': (agent.get('prompt_addendum', '') or '')[:1000],
                'judge': validate_judge_config(agent.get('judge')),
                'coach_guidance': agent.get('coach_guidance', ''),
            })

        if validated_agents:
            validated_groups.append({
                'group_id': group.get('group_id', f'group_{len(validated_groups)}'),
                'label': group.get('label', f'Group {len(validated_groups) + 1}'),
                'execution': group.get('execution') if group.get('execution') in ('parallel', 'sequential') else 'parallel',
                'agents': validated_agents,
            })

    if not validated_groups:
        validated_groups = [{
            'group_id': 'default_parallel',
            'label': 'Review',
            'execution': 'parallel',
            'agents': [
                {
                    'agent_type': t,
                    'depth': 'standard',
                    'focus_areas': [],
                    'prompt_addendum': '',
                    'judge': {'enabled': False, 'max_iterations': 3, 'quality_threshold': 0.8},
                    'coach_guidance': '',
                }
                for t in available_agents
            ],
        }]

    plan['groups'] = validated_groups
    return plan


def build_plan_tool(agent_types: List[str]) -> Dict:
    """Build the Bedrock Converse tool schema dynamically from available agent types.

    Args:
        agent_types: List of valid agent type strings for the enum constraints.

    Returns:
        Tool schema dict for Bedrock Converse toolConfig.
    """
    return {
        'toolSpec': {
            'name': 'create_review_plan',
            'description': 'Create a structured review plan for the document. You MUST call this tool with your plan.',
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'required': ['document_type', 'complexity', 'rationale', 'groups'],
                    'properties': {
                        'document_type': {
                            'type': 'string',
                            'description': 'Classified document type (e.g. microservices_architecture, api_specification, payment_system)',
                        },
                        'complexity': {
                            'type': 'string',
                            'enum': ['low', 'medium', 'high'],
                        },
                        'rationale': {
                            'type': 'string',
                            'description': 'Why you chose this workflow — reference specific things in the document',
                        },
                        'groups': {
                            'type': 'array',
                            'description': 'Ordered list of execution groups',
                            'items': {
                                'type': 'object',
                                'required': ['group_id', 'label', 'execution', 'agents'],
                                'properties': {
                                    'group_id': {'type': 'string'},
                                    'label': {'type': 'string', 'description': 'Human-readable label'},
                                    'execution': {'type': 'string', 'enum': ['parallel', 'sequential']},
                                    'agents': {
                                        'type': 'array',
                                        'items': {
                                            'type': 'object',
                                            'required': ['agent_type', 'depth'],
                                            'properties': {
                                                'agent_type': {'type': 'string', 'enum': agent_types},
                                                'depth': {'type': 'string', 'enum': ['quick', 'standard', 'thorough']},
                                                'focus_areas': {'type': 'array', 'items': {'type': 'string'}},
                                                'prompt_addendum': {'type': 'string', 'description': 'Document-specific guidance for this agent'},
                                                'judge': {
                                                    'type': 'object',
                                                    'description': 'Quality judge coaching config. Enable for complex documents where iterative refinement adds value.',
                                                    'properties': {
                                                        'enabled': {'type': 'boolean', 'description': 'Whether to enable coach loop for this agent'},
                                                        'max_iterations': {'type': 'integer', 'minimum': 1, 'maximum': 5, 'description': 'Max coaching iterations (1-5)'},
                                                        'quality_threshold': {'type': 'number', 'minimum': 0.5, 'maximum': 1.0, 'description': 'Score threshold to pass (0.5-1.0)'},
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                }
            },
        }
    }
