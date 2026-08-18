"""Verify that app.py routes and openapi.yaml paths stay in sync.

Parses both files directly — no hardcoded route lists to go stale.
Catches drift like the abort endpoint that was missing from the spec
for an unknown period.

The openapi.yaml is the API Gateway source of truth (Terraform templatefile).
If a route exists in app.py but not in the spec, it works locally but 404s
in deployed environments. If a path exists in the spec but not in app.py,
API Gateway routes to the Lambda but the Lambda returns 404.
"""

import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent.parent
APP_PY = ROOT / "api" / "rest_api" / "app.py"
OPENAPI_YAML = ROOT / "api" / "openapi.yaml"


def _extract_app_routes() -> set[tuple[str, str]]:
    """Parse app.py and extract (METHOD, path_template) tuples from ROUTES.

    Reads the AST to find the ROUTES list assignment, then extracts the
    first two string elements from each tuple literal.
    """
    source = APP_PY.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "ROUTES":
                    value = node.value
                    routes = set()
                    for elt in value.elts:
                        # Each element is a Tuple(method, path, handler)
                        method = elt.elts[0].value
                        path = elt.elts[1].value
                        routes.add((method, path))
                    return routes

    raise RuntimeError("Could not find ROUTES assignment in app.py")


def _extract_openapi_routes() -> set[tuple[str, str]]:
    """Parse openapi.yaml and extract (METHOD, path) tuples.

    Skips non-HTTP keys like 'parameters' or 'x-amazon-*' that can
    appear under a path item.
    """
    spec = yaml.safe_load(OPENAPI_YAML.read_text())
    http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}
    routes = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.lower() in http_methods:
                routes.add((method.upper(), path))
    return routes


class TestRouteParity:
    """Every route in app.py must exist in openapi.yaml and vice versa."""

    def test_app_routes_exist_in_openapi(self):
        """Routes in app.py missing from openapi.yaml will 404 in deployed
        environments because API Gateway won't create a route for them."""
        app_routes = _extract_app_routes()
        spec_routes = _extract_openapi_routes()
        missing = app_routes - spec_routes
        assert not missing, (
            "Routes in app.py but missing from openapi.yaml "
            "(will 404 in deployed environments):\n"
            + "\n".join(f"  {m} {p}" for m, p in sorted(missing))
        )

    def test_openapi_routes_exist_in_app(self):
        """Routes in openapi.yaml missing from app.py will reach the Lambda
        but get a 404 from the router."""
        app_routes = _extract_app_routes()
        spec_routes = _extract_openapi_routes()
        missing = spec_routes - app_routes
        assert not missing, (
            "Routes in openapi.yaml but missing from app.py "
            "(API Gateway routes to Lambda, Lambda returns 404):\n"
            + "\n".join(f"  {m} {p}" for m, p in sorted(missing))
        )
