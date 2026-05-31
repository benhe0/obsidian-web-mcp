"""JSON serialization helpers."""

from datetime import date, time


def json_default(obj):
    """Fallback serializer for ``json.dumps(..., default=json_default)``.

    YAML frontmatter parses values like ``created: 2024-01-15`` into Python
    ``date``/``datetime``/``time`` objects, which ``json.dumps`` cannot serialize
    by default. Render those as ISO 8601 strings. Any other unexpected type falls
    back to its string form so a single odd frontmatter value can never crash an
    entire response.
    """
    if isinstance(obj, (date, time)):  # date also matches datetime (a subclass)
        return obj.isoformat()
    return str(obj)
