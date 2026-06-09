"""Unit tests for review result processing.

Source: api/core/review_processing.py
Tests the pure functions extracted from workflow/aggregate_results.py:
  - flatten_results: flattens nested group results, accumulates metrics
  - compute_summary: counts findings by severity
  - build_quality_inputs: extracts judge config from plan
"""
from core.review_processing import flatten_results, compute_summary, build_quality_inputs


# ═══════════════════════════════════════════════════════════════════════════
# flatten_results
#
# Takes the nested group_results structure from Step Functions (list of
# groups, each group is a list of agent results) and flattens it into
# a reviews dict keyed by agent_type. Also accumulates token metrics.
# Bugs here mean lost findings or wrong metrics in the dashboard.
# ═══════════════════════════════════════════════════════════════════════════

class TestFlattenResults:

    def test_single_group_single_agent(self):
        group_results = [[
            {
                'agent_type': 'security',
                'findings': [{'id': 'SEC-001', 'title': 'Open port'}],
                'summary': 'One issue found',
                'status': 'completed',
            },
        ]]
        reviews, statuses, metrics = flatten_results(group_results)
        assert 'security' in reviews
        assert len(reviews['security']['findings']) == 1
        assert reviews['security']['summary'] == 'One issue found'
        assert statuses['security']['status'] == 'completed'

    def test_multiple_groups_multiple_agents(self):
        group_results = [
            [
                {'agent_type': 'architecture', 'findings': [{'id': 'A1'}], 'summary': '', 'status': 'completed'},
                {'agent_type': 'security', 'findings': [{'id': 'S1'}, {'id': 'S2'}], 'summary': '', 'status': 'completed'},
            ],
            [
                {'agent_type': 'risk', 'findings': [{'id': 'R1'}], 'summary': '', 'status': 'completed'},
            ],
        ]
        reviews, statuses, metrics = flatten_results(group_results)
        assert len(reviews) == 3
        assert len(reviews['security']['findings']) == 2
        assert len(reviews['risk']['findings']) == 1

    def test_metrics_accumulated_across_agents(self):
        group_results = [[
            {
                'agent_type': 'architecture',
                'findings': [], 'summary': '', 'status': 'completed',
                'metrics': {'total_tokens': 1000, 'input_tokens': 600, 'output_tokens': 400,
                            'cache_read_tokens': 50, 'cache_write_tokens': 30, 'cycle_count': 2,
                            'total_duration_s': 10, 'model_latency_ms': 5000},
            },
            {
                'agent_type': 'security',
                'findings': [], 'summary': '', 'status': 'completed',
                'metrics': {'total_tokens': 2000, 'input_tokens': 1200, 'output_tokens': 800,
                            'cache_read_tokens': 100, 'cache_write_tokens': 60, 'cycle_count': 3,
                            'total_duration_s': 15, 'model_latency_ms': 8000},
            },
        ]]
        _, _, metrics = flatten_results(group_results)
        assert metrics['total_tokens'] == 3000
        assert metrics['input_tokens'] == 1800
        assert metrics['output_tokens'] == 1200
        assert metrics['cache_read_tokens'] == 150
        assert metrics['total_cycles'] == 5
        assert 'architecture' in metrics['by_agent']
        assert 'security' in metrics['by_agent']
        assert metrics['by_agent']['architecture']['total_tokens'] == 1000

    def test_agent_without_metrics(self):
        """Agents that return no metrics should not break accumulation."""
        group_results = [[
            {'agent_type': 'risk', 'findings': [], 'summary': '', 'status': 'completed'},
        ]]
        _, _, metrics = flatten_results(group_results)
        assert metrics['total_tokens'] == 0
        assert 'risk' not in metrics['by_agent']

    def test_malformed_result_without_agent_type_skipped(self):
        """Results missing agent_type should be silently skipped."""
        group_results = [[
            {'findings': [{'id': 'X1'}], 'summary': 'orphan'},
            {'agent_type': 'security', 'findings': [{'id': 'S1'}], 'summary': '', 'status': 'completed'},
        ]]
        reviews, _, _ = flatten_results(group_results)
        assert len(reviews) == 1
        assert 'security' in reviews

    def test_failed_agent_status_preserved(self):
        group_results = [[
            {
                'agent_type': 'architecture',
                'findings': [],
                'summary': '',
                'status': 'failed',
                'status_reason': 'Agent timeout',
            },
        ]]
        reviews, statuses, _ = flatten_results(group_results)
        assert statuses['architecture']['status'] == 'failed'
        assert statuses['architecture']['status_reason'] == 'Agent timeout'
        assert reviews['architecture']['status'] == 'failed'

    def test_empty_group_results(self):
        reviews, statuses, metrics = flatten_results([])
        assert reviews == {}
        assert statuses == {}
        assert metrics['total_tokens'] == 0

    def test_empty_groups(self):
        """Groups that contain no agent results."""
        reviews, _, _ = flatten_results([[], []])
        assert reviews == {}


# ═══════════════════════════════════════════════════════════════════════════
# compute_summary
#
# Counts findings by severity across all agents. This drives the dashboard
# summary cards. Wrong counts here mean misleading risk posture.
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeSummary:

    def test_counts_all_severities(self):
        reviews = {
            'security': {
                'findings': [
                    {'severity': 'Critical'},
                    {'severity': 'High'},
                    {'severity': 'Medium'},
                ],
            },
            'architecture': {
                'findings': [
                    {'severity': 'Low'},
                    {'severity': 'High'},
                ],
            },
        }
        summary = compute_summary(reviews)
        assert summary['total_findings'] == 5
        assert summary['critical_severity'] == 1
        assert summary['high_severity'] == 2
        assert summary['medium_severity'] == 1
        assert summary['low_severity'] == 1
        assert summary['by_agent'] == {'security': 3, 'architecture': 2}

    def test_case_insensitive_severity(self):
        """Severity matching should be case-insensitive — agents may return
        'HIGH', 'High', or 'high'."""
        reviews = {
            'security': {
                'findings': [
                    {'severity': 'HIGH'},
                    {'severity': 'high'},
                    {'severity': 'High'},
                ],
            },
        }
        summary = compute_summary(reviews)
        assert summary['high_severity'] == 3

    def test_unknown_severity_not_counted(self):
        """Findings with unrecognized severity should still be counted in
        total but not in any severity bucket."""
        reviews = {
            'risk': {
                'findings': [
                    {'severity': 'informational'},
                    {'severity': ''},
                ],
            },
        }
        summary = compute_summary(reviews)
        assert summary['total_findings'] == 2
        assert summary['critical_severity'] == 0
        assert summary['high_severity'] == 0
        assert summary['medium_severity'] == 0
        assert summary['low_severity'] == 0

    def test_missing_severity_field(self):
        """Findings without a severity key should not crash."""
        reviews = {
            'security': {
                'findings': [{'title': 'No severity'}],
            },
        }
        summary = compute_summary(reviews)
        assert summary['total_findings'] == 1

    def test_empty_reviews(self):
        summary = compute_summary({})
        assert summary['total_findings'] == 0
        assert summary['by_agent'] == {}

    def test_agent_with_no_findings(self):
        reviews = {
            'architecture': {'findings': []},
            'security': {'findings': [{'severity': 'High'}]},
        }
        summary = compute_summary(reviews)
        assert summary['total_findings'] == 1
        assert summary['by_agent'] == {'architecture': 0, 'security': 1}


# ═══════════════════════════════════════════════════════════════════════════
# build_quality_inputs
#
# Extracts focus_areas and coach_guidance from the plan for each agent
# that produced results. The judge uses these to evaluate quality.
# Wrong extraction means the judge evaluates against wrong criteria.
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildQualityInputs:

    def test_extracts_focus_areas_and_guidance(self):
        reviews = {'security': {'findings': []}, 'architecture': {'findings': []}}
        plan = {
            'groups': [
                {
                    'agents': [
                        {'agent_type': 'security', 'focus_areas': ['IAM', 'encryption'],
                         'coach_guidance': 'Focus on data at rest'},
                        {'agent_type': 'architecture', 'focus_areas': ['scalability'],
                         'coach_guidance': ''},
                    ],
                },
            ],
        }
        inputs = build_quality_inputs(reviews, plan)
        assert len(inputs) == 2
        sec = next(i for i in inputs if i['agent_type'] == 'security')
        assert sec['focus_areas'] == ['IAM', 'encryption']
        assert sec['coach_guidance'] == 'Focus on data at rest'

    def test_agent_not_in_plan_gets_empty_defaults(self):
        """If an agent produced results but isn't in the plan (edge case),
        it should still get an entry with empty focus_areas."""
        reviews = {'risk': {'findings': []}}
        plan = {'groups': [{'agents': [{'agent_type': 'security'}]}]}
        inputs = build_quality_inputs(reviews, plan)
        assert len(inputs) == 1
        assert inputs[0]['agent_type'] == 'risk'
        assert inputs[0]['focus_areas'] == []
        assert inputs[0]['coach_guidance'] == ''

    def test_agent_in_second_group(self):
        """Agent config should be found regardless of which group it's in."""
        reviews = {'risk': {'findings': []}}
        plan = {
            'groups': [
                {'agents': [{'agent_type': 'security', 'focus_areas': ['x']}]},
                {'agents': [{'agent_type': 'risk', 'focus_areas': ['compliance'],
                             'coach_guidance': 'Check ISO'}]},
            ],
        }
        inputs = build_quality_inputs(reviews, plan)
        assert inputs[0]['focus_areas'] == ['compliance']
        assert inputs[0]['coach_guidance'] == 'Check ISO'

    def test_empty_plan(self):
        reviews = {'security': {'findings': []}}
        inputs = build_quality_inputs(reviews, {})
        assert len(inputs) == 1
        assert inputs[0]['focus_areas'] == []

    def test_empty_reviews(self):
        inputs = build_quality_inputs({}, {'groups': []})
        assert inputs == []
