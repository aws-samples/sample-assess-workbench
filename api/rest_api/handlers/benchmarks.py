"""Benchmark request handlers."""
import logging
from typing import Dict, Any
from ..services.benchmark_service import BenchmarkService
from ..utils import success_response, error_response, parse_body

logger = logging.getLogger(__name__)


class BenchmarkHandlers:
    """Handles benchmark-related HTTP requests."""

    def __init__(self, benchmark_service: BenchmarkService):
        self.benchmark_service = benchmark_service

    def create_benchmark(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle POST /benchmarks"""
        try:
            body = parse_body(event)

            name = (body.get('name') or '').strip()
            if not name:
                return error_response(400, 'Missing required field: name')

            document_project_id = (body.get('document_project_id') or '').strip()
            if not document_project_id:
                return error_response(400, 'Missing required field: document_project_id')

            agent_type = (body.get('agent_type') or '').strip()
            if not agent_type:
                return error_response(400, 'Missing required field: agent_type')

            configurations = body.get('configurations', [])
            if not configurations or not isinstance(configurations, list):
                return error_response(400, 'configurations must be a non-empty array')

            # Validate each configuration has required fields
            for i, cfg in enumerate(configurations):
                if not cfg.get('model_id'):
                    return error_response(400, f'configurations[{i}] missing required field: model_id')
                if not cfg.get('label'):
                    return error_response(400, f'configurations[{i}] missing required field: label')

            claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
            created_by = claims.get('sub', '')

            result = self.benchmark_service.create_benchmark(
                name=name,
                document_project_id=document_project_id,
                agent_type=agent_type,
                configurations=configurations,
                created_by=created_by,
            )
            return success_response(result, status_code=201)

        except ValueError as e:
            return error_response(400, str(e))
        except Exception as e:
            logger.error(f"Error creating benchmark: {e}")
            return error_response(500, 'Failed to create benchmark')

    def list_benchmarks(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /benchmarks"""
        try:
            result = self.benchmark_service.list_benchmarks()
            return success_response(result)
        except Exception as e:
            logger.error(f"Error listing benchmarks: {e}")
            return error_response(500, 'Failed to list benchmarks')

    def get_benchmark(self, benchmark_id: str, event: Dict[str, Any],
                      context: Any) -> Dict[str, Any]:
        """Handle GET /benchmarks/{benchmark_id}"""
        try:
            result = self.benchmark_service.get_benchmark(benchmark_id)
            return success_response(result)
        except ValueError as e:
            return error_response(404, str(e))
        except Exception as e:
            logger.error(f"Error getting benchmark: {e}")
            return error_response(500, 'Failed to get benchmark')

    def run_benchmark(self, benchmark_id: str, event: Dict[str, Any],
                      context: Any) -> Dict[str, Any]:
        """Handle POST /benchmarks/{benchmark_id}/run"""
        try:
            result = self.benchmark_service.run_benchmark(benchmark_id)
            return success_response(result, status_code=202)
        except ValueError as e:
            return error_response(400, str(e))
        except Exception as e:
            logger.error(f"Error running benchmark: {e}")
            return error_response(500, 'Failed to run benchmark')

    def delete_benchmark(self, benchmark_id: str, event: Dict[str, Any],
                         context: Any) -> Dict[str, Any]:
        """Handle DELETE /benchmarks/{benchmark_id}"""
        try:
            result = self.benchmark_service.delete_benchmark(benchmark_id)
            return success_response(result)
        except ValueError as e:
            return error_response(404, str(e))
        except Exception as e:
            logger.error(f"Error deleting benchmark: {e}")
            return error_response(500, 'Failed to delete benchmark')
