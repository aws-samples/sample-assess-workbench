"""Benchmark business logic."""
import json
import os
import uuid
from typing import Dict, Any, List

import boto3

from ..data_access.benchmarks import BenchmarkDataAccess
from ..data_access import DynamoDBDataAccess, S3DataAccess


class BenchmarkService:
    """Handles benchmark creation, execution, and retrieval."""

    def __init__(self, dynamodb: DynamoDBDataAccess, s3: S3DataAccess,
                 benchmark_db: BenchmarkDataAccess):
        self.dynamodb = dynamodb
        self.s3 = s3
        self.benchmark_db = benchmark_db

    def create_benchmark(self, name: str, document_project_id: str,
                         agent_type: str, configurations: List[Dict[str, Any]],
                         created_by: str = '') -> Dict[str, Any]:
        """Create a new benchmark definition.

        Args:
            name: Human-readable name
            document_project_id: Source project for the document
            agent_type: Agent type to benchmark
            configurations: List of model/prompt configs
            created_by: User sub

        Returns:
            Created benchmark summary
        """
        # Validate the source project exists
        project = self.dynamodb.get_project(document_project_id)
        if not project:
            raise ValueError(f'Source project not found: {document_project_id}')

        benchmark_id = f'bench_{uuid.uuid4().hex[:8]}'

        # Ensure each config has a config_id
        for cfg in configurations:
            if not cfg.get('config_id'):
                cfg['config_id'] = cfg.get('label', '').lower().replace(' ', '_')[:32] or uuid.uuid4().hex[:8]

        item = self.benchmark_db.create_benchmark(
            benchmark_id=benchmark_id,
            name=name,
            document_project_id=document_project_id,
            agent_type=agent_type,
            configurations=configurations,
            created_by=created_by,
        )

        return {
            'benchmark_id': item['benchmark_id'],
            'name': item['name'],
            'document_project_id': item['document_project_id'],
            'agent_type': item['agent_type'],
            'configurations': item['configurations'],
            'status': item['status'],
            'created_at': item['created_at'],
        }

    def list_benchmarks(self, limit: int = 50) -> Dict[str, Any]:
        """List all benchmarks.

        Returns:
            Dict with benchmarks list and count
        """
        items = self.benchmark_db.list_benchmarks(limit=limit)
        benchmarks = [
            {
                'benchmark_id': it['benchmark_id'],
                'name': it['name'],
                'document_project_id': it['document_project_id'],
                'agent_type': it['agent_type'],
                'status': it.get('status', 'pending'),
                'created_at': it['created_at'],
            }
            for it in items
        ]
        return {'benchmarks': benchmarks, 'count': len(benchmarks)}

    def get_benchmark(self, benchmark_id: str) -> Dict[str, Any]:
        """Get benchmark with all run results.

        Args:
            benchmark_id: Benchmark identifier

        Returns:
            Benchmark metadata + runs

        Raises:
            ValueError: If benchmark not found
        """
        item = self.benchmark_db.get_benchmark(benchmark_id)
        if not item:
            raise ValueError(f'Benchmark not found: {benchmark_id}')

        runs = self.benchmark_db.get_benchmark_runs(benchmark_id)
        run_results = [
            {k: v for k, v in r.items() if k not in ('PK', 'SK')}
            for r in runs
        ]

        result = {
            'benchmark_id': item['benchmark_id'],
            'name': item['name'],
            'document_project_id': item['document_project_id'],
            'agent_type': item['agent_type'],
            'configurations': item['configurations'],
            'status': item.get('status', 'pending'),
            'created_at': item['created_at'],
            'runs': run_results,
        }
        if item.get('error_message'):
            result['error_message'] = item['error_message']
        return result

    def run_benchmark(self, benchmark_id: str) -> Dict[str, Any]:
        """Trigger benchmark execution via the runner Lambda.

        Invokes the benchmark-runner Lambda asynchronously. Each configuration
        runs in parallel inside that Lambda.

        Args:
            benchmark_id: Benchmark identifier

        Returns:
            Execution status

        Raises:
            ValueError: If benchmark not found or already running
        """
        item = self.benchmark_db.get_benchmark(benchmark_id)
        if not item:
            raise ValueError(f'Benchmark not found: {benchmark_id}')
        if item.get('status') == 'running':
            raise ValueError('Benchmark is already running')

        # Resolve the source document
        project = self.dynamodb.get_project(item['document_project_id'])
        if not project:
            raise ValueError(f'Source project not found: {item["document_project_id"]}')

        self.benchmark_db.update_benchmark_status(benchmark_id, 'running')

        # Invoke the runner Lambda asynchronously
        lambda_client = boto3.client('lambda')
        runner_function = os.environ.get('BENCHMARK_RUNNER_FUNCTION', '')
        if not runner_function:
            raise ValueError('BENCHMARK_RUNNER_FUNCTION not configured')

        payload = {
            'benchmark_id': benchmark_id,
            'agent_type': item['agent_type'],
            'configurations': item['configurations'],
            's3_bucket': project['s3_bucket'],
            's3_key': project['s3_key'],
            'document_project_id': item['document_project_id'],
        }

        lambda_client.invoke(
            FunctionName=runner_function,
            InvocationType='Event',  # async
            Payload=json.dumps(payload).encode('utf-8'),
        )

        return {
            'benchmark_id': benchmark_id,
            'status': 'running',
            'configurations_count': len(item['configurations']),
        }

    def delete_benchmark(self, benchmark_id: str) -> Dict[str, Any]:
        """Delete a benchmark and all its runs.

        Args:
            benchmark_id: Benchmark identifier

        Returns:
            Deletion summary

        Raises:
            ValueError: If benchmark not found
        """
        item = self.benchmark_db.get_benchmark(benchmark_id)
        if not item:
            raise ValueError(f'Benchmark not found: {benchmark_id}')

        deleted_count = self.benchmark_db.delete_benchmark(benchmark_id)
        return {'benchmark_id': benchmark_id, 'deleted': True, 'items_deleted': deleted_count}
