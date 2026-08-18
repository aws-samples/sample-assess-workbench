"""Build Pydantic models dynamically from declarative finding schema config.

The finding schema is defined in agent.yaml (and stored in the DynamoDB
agent registry). This module constructs Pydantic BaseModel classes at
runtime using pydantic.create_model(), eliminating the need for
hand-written model classes per agent.

Usage:
    schema_config = agent_yaml["finding_schema"]
    ReviewModel = build_review_model("security", schema_config)
    # Pass ReviewModel to Strands as structured_output_model
"""

import itertools
from typing import Any, List, Literal

from pydantic import BaseModel, Field, create_model


# Type mapping from YAML string types to Python types.
# When a field has an "enum" list, the builder uses Literal[...] instead
# of the base type — see build_finding_model() below.
TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list[str]": List[str],
}

COMMON_FINDING_FIELDS: dict[str, tuple[type, Any]] = {
    "id": (str, Field(description="Unique finding ID")),
    "title": (str, Field(description="Brief title, max 8 words")),
    "description": (
        str,
        Field(
            description=(
                "Detailed description. Use markdown: **bold**, bullet points, "
                "blank lines between paragraphs."
            )
        ),
    ),
    "recommendation": (
        str,
        Field(
            description=(
                "Specific, actionable recommendation. Use markdown: numbered "
                "lists, bullet points, **bold**."
            )
        ),
    ),
    "references": (
        List[str],
        Field(default_factory=list, description="References to document sections"),
    ),
}


def _normalize_matrix_key(key: Any) -> tuple[str, ...]:
    """Normalize a matrix key to a tuple of strings.

    Matrix keys arrive in different formats depending on the source:
    - tuple: from Python dicts in tests (e.g., ("likely", "major"))
    - list: from YAML sequence keys (e.g., [likely, major])
    - str: from YAML string keys (e.g., "likely,major")

    Args:
        key: The raw matrix key.

    Returns:
        A tuple of stripped strings.
    """
    if isinstance(key, tuple):
        return key
    if isinstance(key, list):
        return tuple(key)
    if isinstance(key, str):
        return tuple(part.strip() for part in key.split(","))
    return (str(key),)


def _normalize_matrix(raw_matrix: dict) -> dict[tuple[str, ...], str]:
    """Normalize all keys in a severity derivation matrix.

    Args:
        raw_matrix: The matrix dict as loaded from YAML or Python.

    Returns:
        A dict with tuple keys and string values.
    """
    return {_normalize_matrix_key(k): v for k, v in raw_matrix.items()}


def _validate_severity_matrix(schema_config: dict[str, Any]) -> None:
    """Validate that the severity derivation matrix covers all enum combinations.

    Called at build time (agent startup) so incomplete matrices fail fast
    with a clear error pointing at the config — not at runtime when a
    finding happens to hit a missing key.

    Args:
        schema_config: The finding_schema dict from agent.yaml.

    Raises:
        ValueError: If any input field lacks enum values, or if the matrix
            is missing entries for valid enum combinations.
    """
    derivation = schema_config.get("severity_derivation")
    if not derivation:
        return

    fields = schema_config.get("fields", {})
    input_names = derivation["inputs"]
    matrix = _normalize_matrix(derivation["matrix"])

    # Get enum values for each input field
    enum_lists: list[list[str]] = []
    for name in input_names:
        field_def = fields.get(name, {})
        enums = field_def.get("enum")
        if not enums:
            raise ValueError(f"Severity derivation input '{name}' has no enum values defined")
        enum_lists.append(enums)

    # Check every combination exists in the matrix
    missing = []
    for combo in itertools.product(*enum_lists):
        if combo not in matrix:
            missing.append(combo)

    if missing:
        raise ValueError(
            f"Severity derivation matrix is missing {len(missing)} entries: "
            f"{missing[:5]}{'...' if len(missing) > 5 else ''}"
        )


def build_finding_model(agent_type: str, schema_config: dict[str, Any]) -> type[BaseModel]:
    """Build a Pydantic Finding model from a declarative schema config.

    Returns the Finding model only — use build_review_model() to get the
    Review wrapper that Strands structured output needs. Exposed separately
    so tests, derive_severity(), and frontend schema introspection can work
    with individual findings without unwrapping a Review container.

    Args:
        agent_type: Agent type string (used for class naming).
        schema_config: The finding_schema dict from agent.yaml.

    Returns:
        A dynamically-created Pydantic BaseModel class for a single finding.

    Raises:
        ValueError: If severity_source is "derived" and the matrix is
            incomplete or input fields lack enum definitions.
    """
    # Validate severity matrix completeness at build time
    if schema_config.get("severity_source") == "derived":
        _validate_severity_matrix(schema_config)

    fields: dict[str, Any] = {}

    # Add common fields
    fields.update(COMMON_FINDING_FIELDS)

    # Add severity — handling differs based on severity_source.
    # When "derived", severity is computed post-parse from other fields
    # (e.g., likelihood × consequence matrix). We include it as optional
    # with default="" so the Pydantic model shape matches the final output
    # shape (model_dump() always has severity), but the LLM doesn't waste
    # effort producing a value that gets overwritten.
    # When "direct", severity is required — the LLM must assess it.
    severity_levels = schema_config.get("severity_levels", ["high", "medium", "low"])
    if schema_config.get("severity_source") == "derived":
        fields["severity"] = (
            str,
            Field(default="", description="Derived automatically — do not set"),
        )
    else:
        severity_desc = f"Severity level: {', '.join(severity_levels)}"
        fields["severity"] = (str, Field(description=severity_desc))

    # Add agent-specific fields from the schema config
    for field_name, field_def in schema_config.get("fields", {}).items():
        python_type = TYPE_MAP.get(field_def["type"], str)
        required = field_def.get("required", False)
        default = field_def.get("default", "" if python_type is str else None)
        description = field_def.get("description", "")

        # If the field has an enum list, use Literal[...] instead of the
        # base type. This puts the allowed values into the JSON schema
        # that the model sees via structured output, giving schema-level
        # enforcement rather than relying on the description alone.
        enum_values = field_def.get("enum")
        if enum_values:
            python_type = Literal[tuple(enum_values)]

        # Optional fields use the base type with a default value (e.g., str
        # with default=""), not Optional[str]. This keeps the contract simple —
        # fields are always their declared type, never None. Downstream code
        # doesn't need null checks, and structured output JSON stays clean.
        if required:
            fields[field_name] = (python_type, Field(description=description))
        else:
            fields[field_name] = (
                python_type,
                Field(default=default, description=description),
            )

    return create_model(
        f"{agent_type.title().replace('_', '')}Finding",
        **fields,
    )


def build_review_model(agent_type: str, schema_config: dict[str, Any]) -> type[BaseModel]:
    """Build a Review model (findings list + summary) wrapping the Finding model.

    This is the model passed to Strands as structured_output_model. The
    Review wrapper is identical for every agent — only the Finding model
    inside it varies.

    Args:
        agent_type: Agent type string (used for class naming).
        schema_config: The finding_schema dict from agent.yaml.

    Returns:
        A dynamically-created Pydantic BaseModel class for a full review.
    """
    finding_model = build_finding_model(agent_type, schema_config)
    return create_model(
        f"{agent_type.title().replace('_', '')}Review",
        findings=(List[finding_model], Field(description="List of findings")),
        summary=(str, Field(description="Overall assessment")),
    )


def derive_severity(findings: list[dict[str, Any]], schema_config: dict[str, Any]) -> None:
    """Apply declarative severity derivation to parsed findings.

    Called post-parse when severity_source is "derived". Mutates findings
    in place — replaces whatever the LLM produced for severity with the
    matrix-derived value.

    The matrix is guaranteed to be complete — _validate_severity_matrix()
    checked every enum combination at build time. An unconditional lookup
    is safe here.

    Args:
        findings: List of finding dicts (already parsed from structured output).
        schema_config: The finding_schema dict from agent.yaml.

    Raises:
        ValueError: If a finding's field values don't match any matrix entry.
    """
    derivation = schema_config.get("severity_derivation")
    if not derivation:
        return

    input_fields = derivation["inputs"]
    matrix = _normalize_matrix(derivation["matrix"])

    for finding in findings:
        key = tuple(finding[f] for f in input_fields)
        if key not in matrix:
            raise ValueError(
                f"Severity derivation failed: no matrix entry for "
                f"{dict(zip(input_fields, key))}. "
                f"Check that field values match the enum definitions."
            )
        finding["severity"] = matrix[key]
