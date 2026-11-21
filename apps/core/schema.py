# apps/core/schema.py
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

TYPE_MAP = {
    int: OpenApiTypes.INT,
    str: OpenApiTypes.STR,
    bool: OpenApiTypes.BOOL,
    float: OpenApiTypes.FLOAT,
}


def auto_schema(
    summary: str = "",
    params: dict[str, type] | None = None,
    files: list[str] | None = None,
    request=None,
    response=None,
    many: bool = False,
):
    """
    Compact @extend_schema wrapper for APIViews.
    - Suffix a param with '*' (e.g. {"id*": int}) to mark it required.
    - Pass files=["file"] (or ["image*"]) to render file upload pickers in Swagger UI.
    """
    parameters = []
    for raw_name, py_type in (params or {}).items():
        is_required = raw_name.endswith("*")
        clean_name = raw_name.rstrip("*")
        parameters.append(
            OpenApiParameter(
                name=clean_name,
                type=TYPE_MAP.get(py_type, OpenApiTypes.STR),
                location=OpenApiParameter.QUERY,
                required=is_required,
            )
        )

    # Build multipart/form-data file upload schema if `files` is provided
    resolved_request = request
    if files:
        properties = {}
        required_fields = []
        for raw_file in files:
            is_required = raw_file.endswith("*")
            clean_file = raw_file.rstrip("*")
            properties[clean_file] = {"type": "string", "format": "binary"}
            if is_required:
                required_fields.append(clean_file)

        schema_body = {"type": "object", "properties": properties}
        if required_fields:
            schema_body["required"] = required_fields

        resolved_request = {"multipart/form-data": schema_body}

    responses = None
    if response is not None:
        responses = response(many=True) if (many and callable(response)) else response

    return extend_schema(
        summary=summary,
        parameters=parameters,
        request=resolved_request,
        responses=responses,
    )
