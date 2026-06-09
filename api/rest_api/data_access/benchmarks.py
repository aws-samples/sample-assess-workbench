"""DynamoDB data access for benchmark records."""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from boto3.dynamodb.conditions import Key


class BenchmarkDataAccess:
    """Handles DynamoDB operations for benchmarks."""

    def __init__(self, table):
        """Initialize with a DynamoDB table resource.

        Args:
            table: boto3 DynamoDB Table resource (shared from DynamoDBDataAccess)
        """
        self.table = table

    def create_benchmark(self, benchmark_id: str, name: str,
                         document_project_id: str, agent_type: str,
                         configurations: List[Dict[str, Any]],
                         created_by: str = '') -> Dict[str, Any]:
        """Create a benchmark definition.

        Args:
            benchmark_id: Unique benchmark identifier
            name: Human-readable benchmark name
            document_project_id: Source project ID for the document
            agent_type: Agent type to benchmark
            configurations: List of model/prompt configurations
            created_by: User who created the benchmark

        Returns:
            Created benchmark item
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds')
        item = {
            'PK': f'BENCHMARK#{benchmark_id}',
            'SK': 'METADATA',
            'GSI1PK': 'BENCHMARK',
            'GSI1SK': timestamp,
            'benchmark_id': benchmark_id,
            'name': name,
            'document_project_id': document_project_id,
            'agent_type': agent_type,
            'configurations': configurations,
            'status': 'pending',
            'created_at': timestamp,
            'created_by': created_by,
        }
        self.table.put_item(Item=item)
        return item

    def get_benchmark(self, benchmark_id: str) -> Optional[Dict[str, Any]]:
        """Get benchmark metadata.

        Args:
            benchmark_id: Benchmark identifier

        Returns:
            Benchmark item or None
        """
        response = self.table.get_item(
            Key={'PK': f'BENCHMARK#{benchmark_id}', 'SK': 'METADATA'}
        )
        return response.get('Item')

    def list_benchmarks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all benchmarks, newest first.

        Args:
            limit: Maximum number of results

        Returns:
            List of benchmark metadata items
        """
        response = self.table.query(
            IndexName='GSI1',
            KeyConditionExpression=Key('GSI1PK').eq('BENCHMARK'),
            ScanIndexForward=False,
            Limit=limit,
        )
        return response.get('Items', [])

    def update_benchmark_status(self, benchmark_id: str, status: str) -> None:
        """Update benchmark status.

        Args:
            benchmark_id: Benchmark identifier
            status: New status (pending, running, completed, failed)
        """
        self.table.update_item(
            Key={'PK': f'BENCHMARK#{benchmark_id}', 'SK': 'METADATA'},
            UpdateExpression='SET #status = :status, updated_at = :ts',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': status,
                ':ts': datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds'),
            },
        )

    def put_benchmark_run(self, benchmark_id: str, config_id: str,
                          data: Dict[str, Any]) -> Dict[str, Any]:
        """Store a benchmark run result.

        Args:
            benchmark_id: Benchmark identifier
            config_id: Configuration identifier
            data: Run result data (findings, scores, metrics)

        Returns:
            Stored item
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds')
        item = {
            'PK': f'BENCHMARK#{benchmark_id}',
            'SK': f'RUN#{config_id}',
            'config_id': config_id,
            'completed_at': timestamp,
            **data,
        }
        self.table.put_item(Item=item)
        return item

    def get_benchmark_runs(self, benchmark_id: str) -> List[Dict[str, Any]]:
        """Get all run results for a benchmark.

        Args:
            benchmark_id: Benchmark identifier

        Returns:
            List of run result items
        """
        response = self.table.query(
            KeyConditionExpression=(
                Key('PK').eq(f'BENCHMARK#{benchmark_id}')
                & Key('SK').begins_with('RUN#')
            ),
        )
        return response.get('Items', [])

    def delete_benchmark(self, benchmark_id: str) -> int:
        """Delete a benchmark and all its run results.

        Args:
            benchmark_id: Benchmark identifier

        Returns:
            Number of items deleted
        """
        response = self.table.query(
            KeyConditionExpression=Key('PK').eq(f'BENCHMARK#{benchmark_id}'),
        )
        items = response.get('Items', [])

        with self.table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})

        return len(items)
