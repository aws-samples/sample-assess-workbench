"""Analytics business logic — aggregates quality scores, feedback, and trends."""
from typing import Dict, Any, List, Optional
from ..data_access import DynamoDBDataAccess
from ..data_access.benchmarks import BenchmarkDataAccess


class AnalyticsService:
    """Aggregates data from reviews, benchmarks, and feedback for the dashboard."""

    def __init__(self, dynamodb: DynamoDBDataAccess, benchmark_db: BenchmarkDataAccess):
        self.dynamodb = dynamodb
        self.benchmark_db = benchmark_db

    def get_summary(self, user_sub: str = '') -> Dict[str, Any]:
        """Aggregated quality scores, feedback rates, and recent review stats.

        Scans completed projects, extracts quality_scores from their latest
        reviews, and computes per-agent averages. Also aggregates feedback.

        When user_sub is provided, only that user's projects are included.
        When empty (admin), all projects are included.

        Args:
            user_sub: Cognito user sub to scope results. Empty string means
                all projects (admin view).

        Returns:
            Dict with agent_scores, feedback_summary, review_count, recent_reviews
        """
        if user_sub:
            projects = self.dynamodb.list_projects_for_user(user_sub, limit=100)
        else:
            projects = self.dynamodb.list_projects(limit=100)
        completed = [p for p in projects if p.get('status') == 'completed']

        # Collect quality scores and feedback across all completed reviews
        agent_scores: Dict[str, List[Dict[str, float]]] = {}
        agent_finding_counts: Dict[str, int] = {}
        recent_reviews: List[Dict[str, Any]] = []
        total_feedback = {'up': 0, 'down': 0}
        agent_feedback: Dict[str, Dict[str, int]] = {}

        for project in completed[:50]:  # Cap to avoid timeout
            pid = project['project_id']
            review = self.dynamodb.get_latest_review(pid)
            if not review:
                continue

            findings = review.get('findings', {})
            reviews_data = findings.get('reviews', {})
            review_entry = {
                'project_id': pid,
                'project_name': project.get('name', ''),
                'created_at': review.get('created_at', ''),
                'scores': {},
            }

            for agent_type, agent_data in reviews_data.items():
                qs = agent_data.get('quality_scores')
                if qs and isinstance(qs, dict):
                    if agent_type not in agent_scores:
                        agent_scores[agent_type] = []
                    agent_scores[agent_type].append(qs)
                    review_entry['scores'][agent_type] = qs.get('overall', 0)

                # Count total findings per agent (across all reviews)
                finding_count = len(agent_data.get('findings', []))
                agent_finding_counts[agent_type] = agent_finding_counts.get(agent_type, 0) + finding_count

            recent_reviews.append(review_entry)

            # Aggregate feedback
            feedback_items = self.dynamodb.get_feedback(pid)
            for fb in feedback_items:
                val = fb.get('value', '')
                at = fb.get('agent_type', '')
                if val in ('up', 'down'):
                    total_feedback[val] += 1
                    if at not in agent_feedback:
                        agent_feedback[at] = {'up': 0, 'down': 0}
                    agent_feedback[at][val] += 1

        # Compute per-agent average scores
        avg_scores = {}
        for agent_type, scores_list in agent_scores.items():
            n = len(scores_list)
            avg = {}
            for criterion in ('completeness', 'specificity', 'actionability', 'overall'):
                vals = [s.get(criterion, 0) for s in scores_list if criterion in s]
                avg[criterion] = round(sum(vals) / len(vals), 3) if vals else 0
            avg['review_count'] = n
            avg_scores[agent_type] = avg

        # Feedback summary per agent
        feedback_summary = {}
        for at, counts in agent_feedback.items():
            total = counts['up'] + counts['down']
            feedback_summary[at] = {
                'up': counts['up'],
                'down': counts['down'],
                'total': total,
                'total_findings': agent_finding_counts.get(at, 0),
                'agreement_rate': round(counts['up'] / total, 3) if total > 0 else 0,
            }

        # Sort recent reviews by date descending
        recent_reviews.sort(key=lambda r: r.get('created_at', ''), reverse=True)

        return {
            'agent_scores': avg_scores,
            'feedback_summary': feedback_summary,
            'total_feedback': total_feedback,
            'review_count': len(completed),
            'recent_reviews': recent_reviews[:20],
        }

    def get_trends(self, agent_type: Optional[str] = None,
                   limit: int = 30, user_sub: str = '') -> Dict[str, Any]:
        """Time series quality data for trend charts.

        When user_sub is provided, only that user's projects are included.
        When empty (admin), all projects are included.

        Args:
            agent_type: Optional filter by agent type.
            limit: Max number of data points.
            user_sub: Cognito user sub to scope results. Empty string means
                all projects (admin view).

        Returns:
            Dict with data_points list (date, agent, scores)
        """
        if user_sub:
            projects = self.dynamodb.list_projects_for_user(user_sub, limit=100)
        else:
            projects = self.dynamodb.list_projects(limit=100)
        completed = [p for p in projects if p.get('status') == 'completed']

        data_points: List[Dict[str, Any]] = []

        for project in completed:
            pid = project['project_id']
            review = self.dynamodb.get_latest_review(pid)
            if not review:
                continue

            findings = review.get('findings', {})
            reviews_data = findings.get('reviews', {})

            for at, agent_data in reviews_data.items():
                if agent_type and at != agent_type:
                    continue
                qs = agent_data.get('quality_scores')
                if qs and isinstance(qs, dict):
                    data_points.append({
                        'date': review.get('created_at', ''),
                        'project_id': pid,
                        'project_name': project.get('name', ''),
                        'agent_type': at,
                        'scores': {
                            'completeness': qs.get('completeness', 0),
                            'specificity': qs.get('specificity', 0),
                            'actionability': qs.get('actionability', 0),
                            'overall': qs.get('overall', 0),
                        },
                    })

        # Sort by date ascending for time series
        data_points.sort(key=lambda d: d.get('date', ''))

        return {'data_points': data_points[-limit:], 'count': len(data_points)}

    def verify_project_ownership(self, project_id: str, user_sub: str) -> Dict[str, Any]:
        """Verify the requesting user owns the project.

        Args:
            project_id: Project identifier.
            user_sub: Cognito user sub from JWT.

        Returns:
            Raw project item if the user owns it.

        Raises:
            KeyError: If the project does not exist.
            PermissionError: If the user does not own the project.
        """
        return self.dynamodb.verify_project_ownership(project_id, user_sub)

    def get_coverage(self, project_id: str) -> Dict[str, Any]:
        """Coverage matrix data — findings by document section per agent.

        Args:
            project_id: Project identifier

        Returns:
            Dict with matrix (section → agent → finding count) and findings detail

        Raises:
            ValueError: If project not found
        """
        project = self.dynamodb.get_project(project_id)
        if not project:
            raise ValueError(f'Project not found: {project_id}')

        review = self.dynamodb.get_latest_review(project_id)
        if not review:
            return {'matrix': {}, 'sections': [], 'agents': [], 'findings_by_section': {}}

        findings_data = review.get('findings', {})
        reviews_data = findings_data.get('reviews', {})

        # Build section → agent → findings mapping
        section_map: Dict[str, Dict[str, List[Dict]]] = {}
        agents_seen = set()

        for agent_type, agent_data in reviews_data.items():
            agents_seen.add(agent_type)
            for finding in agent_data.get('findings', []):
                refs = finding.get('references', [])
                if not refs:
                    refs = ['(no reference)']
                for ref in refs:
                    section = ref.strip()
                    if section not in section_map:
                        section_map[section] = {}
                    if agent_type not in section_map[section]:
                        section_map[section][agent_type] = []
                    section_map[section][agent_type].append({
                        'id': finding.get('id', ''),
                        'title': finding.get('title', ''),
                        'severity': finding.get('severity', ''),
                    })

        # Build count matrix
        sections = sorted(section_map.keys())
        agents = sorted(agents_seen)
        matrix = {}
        for section in sections:
            matrix[section] = {}
            for agent in agents:
                matrix[section][agent] = len(section_map.get(section, {}).get(agent, []))

        return {
            'matrix': matrix,
            'sections': sections,
            'agents': agents,
            'findings_by_section': section_map,
        }
