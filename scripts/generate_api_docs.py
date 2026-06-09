#!/usr/bin/env python3
"""Generate API reference markdown from the OpenAPI spec.

Reads api/openapi.yaml, strips AWS-specific extensions and template variables,
and produces a clean markdown file at frontend/src/docs/api-reference.md.

Usage: python3 scripts/generate_api_docs.py
"""
import re
import sys
from pathlib import Path

import yaml


def load_spec(path: Path) -> dict:
    """Load the OpenAPI spec, stripping template variables."""
    text = path.read_text()
    # Replace Terraform template variables with placeholders
    text = re.sub(r'\$\{lambda_invoke_arn\}', 'arn:aws:lambda:*:*:function:api', text)
    text = re.sub(r'\$\{cognito_client_id\}', '<client_id>', text)
    text = re.sub(r'\$\{cognito_issuer_url\}', 'https://cognito-idp.<region>.amazonaws.com/<pool_id>', text)
    return yaml.safe_load(text)


def strip_aws_extensions(obj):
    """Recursively remove x-amazon-apigateway-* keys."""
    if isinstance(obj, dict):
        return {k: strip_aws_extensions(v) for k, v in obj.items()
                if not k.startswith('x-amazon-apigateway')}
    if isinstance(obj, list):
        return [strip_aws_extensions(i) for i in obj]
    return obj


def resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref pointer like #/components/schemas/Finding."""
    parts = ref.lstrip('#/').split('/')
    node = spec
    for p in parts:
        node = node.get(p, {})
    return node


def schema_to_fields(spec: dict, schema: dict, indent: int = 0) -> list[str]:
    """Convert a schema to a list of field description lines."""
    lines = []
    if '$ref' in schema:
        schema = resolve_ref(spec, schema['$ref'])

    props = schema.get('properties', {})
    required = set(schema.get('required', []))

    for name, prop in props.items():
        if '$ref' in prop:
            prop = resolve_ref(spec, prop['$ref'])
        ptype = prop.get('type', 'object')
        desc = prop.get('description', '')
        req = ' *(required)*' if name in required else ''
        prefix = '  ' * indent
        lines.append(f"{prefix}- `{name}` ({ptype}){req} — {desc}" if desc
                     else f"{prefix}- `{name}` ({ptype}){req}")

        # Recurse into nested objects
        if ptype == 'object' and 'properties' in prop:
            lines.extend(schema_to_fields(spec, prop, indent + 1))
        if ptype == 'array' and 'items' in prop:
            items = prop['items']
            if '$ref' in items:
                items = resolve_ref(spec, items['$ref'])
            if items.get('type') == 'object' and 'properties' in items:
                lines.append(f"{'  ' * (indent + 1)}*Array items:*")
                lines.extend(schema_to_fields(spec, items, indent + 2))

    return lines


def _format_parameters(spec: dict, params: list) -> list[str]:
    """Format the parameters section for an endpoint."""
    lines = ["**Parameters:**", ""]
    for p in params:
        if '$ref' in p:
            p = resolve_ref(spec, p['$ref'])
        pname = p.get('name', '')
        pin = p.get('in', '')
        pdesc = p.get('description', '')
        preq = '*(required)*' if p.get('required') else '*(optional)*'
        lines.append(f"- `{pname}` ({pin}) {preq} — {pdesc}" if pdesc
                     else f"- `{pname}` ({pin}) {preq}")
    lines.append("")
    return lines


def _format_request_body(spec: dict, body: dict) -> list[str]:
    """Format the request body section for an endpoint."""
    content = body.get('content', {})
    json_schema = content.get('application/json', {}).get('schema', {})
    if not json_schema:
        return []
    return ["**Request body:**", "", *schema_to_fields(spec, json_schema), ""]


def _format_response(spec: dict, responses: dict) -> list[str]:
    """Format the success response section for an endpoint."""
    success_codes = [c for c in responses if c.startswith('2')]
    if not success_codes:
        return []
    code = success_codes[0]
    resp = responses[code]
    lines = [f"**Response ({code}):** {resp.get('description', '')}"]
    resp_schema = resp.get('content', {}).get('application/json', {}).get('schema', {})
    if resp_schema and resp_schema.get('properties'):
        lines.append("")
        lines.extend(schema_to_fields(spec, resp_schema))
    lines.append("")
    return lines


def _format_endpoint(spec: dict, method: str, path: str, op: dict) -> list[str]:
    """Format a single API endpoint."""
    lines = [f"### `{method} {path}`"]
    summary = op.get('summary', '')
    if summary:
        lines.append(f"**{summary}**")
    lines.append("")

    desc = op.get('description', '').strip()
    if desc:
        short = ' '.join(desc.split('\n')[:3]).strip()
        if len(short) > 200:
            short = short[:200] + '...'
        lines.extend([short, ""])

    params = op.get('parameters', [])
    if params:
        lines.extend(_format_parameters(spec, params))

    body = op.get('requestBody', {})
    if body:
        lines.extend(_format_request_body(spec, body))

    responses = op.get('responses', {})
    lines.extend(_format_response(spec, responses))

    lines.extend(["---", ""])
    return lines


def _group_by_tag(spec: dict) -> dict[str, list]:
    """Group API paths by their first tag."""
    tag_paths: dict[str, list] = {}
    for path, methods in sorted(spec.get('paths', {}).items()):
        for method, op in methods.items():
            if method in ('parameters', 'summary', 'description'):
                continue
            tags = op.get('tags', ['other'])
            tag = tags[0] if tags else 'other'
            if tag not in tag_paths:
                tag_paths[tag] = []
            tag_paths[tag].append((method.upper(), path, op))
    return tag_paths


def generate_markdown(spec: dict) -> str:
    """Generate the API reference markdown."""
    spec = strip_aws_extensions(spec)
    lines = [
        "# API Reference",
        "",
        f"**{spec['info']['title']}** v{spec['info']['version']}",
        "",
        "## Authentication",
        "",
        "All endpoints require a Bearer token (Cognito JWT) in the Authorization header:",
        "",
        "```",
        "Authorization: Bearer <id_token>",
        "```",
        "",
        "Tokens expire after 1 hour. The `/health` endpoint is the only exception (no auth required).",
        "",
    ]

    for tag, endpoints in _group_by_tag(spec).items():
        lines.append(f"## {tag.replace('_', ' ').title()}")
        lines.append("")
        for method, path, op in endpoints:
            lines.extend(_format_endpoint(spec, method, path, op))

    return '\n'.join(lines)


def main():
    root = Path(__file__).parent.parent
    spec_path = root / 'api' / 'openapi.yaml'
    output_path = root / 'frontend' / 'src' / 'docs' / 'api-reference.md'

    if not spec_path.exists():
        print(f"❌ OpenAPI spec not found: {spec_path}")
        sys.exit(1)

    spec = load_spec(spec_path)
    markdown = generate_markdown(spec)
    output_path.write_text(markdown)
    print(f"✓ Generated {output_path} ({len(markdown)} chars)")


if __name__ == '__main__':
    main()
