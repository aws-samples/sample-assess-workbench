"""Request handlers for API endpoints."""
from .projects import ProjectHandlers
from .reviews import ReviewHandlers
from .contexts import ContextHandlers
from .feedback import FeedbackHandlers
from .benchmarks import BenchmarkHandlers
from .analytics import AnalyticsHandlers
from .admin import AdminHandlers
from .standards import StandardsHandlers

__all__ = ['ProjectHandlers', 'ReviewHandlers', 'ContextHandlers', 'FeedbackHandlers',
           'BenchmarkHandlers', 'AnalyticsHandlers', 'AdminHandlers', 'StandardsHandlers']
