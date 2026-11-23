# utils/report_filters.py
from datetime import datetime


VALID_REPORT_PERIODS = {"monthly", "quarterly", "annual", "custom"}
VALID_EXPORT_FORMATS = {"xlsx", "pdf", "csv"}


def validate_report_params(
    request,
    allowed_periods: set[str] | None = None,
    require_format: bool = False,
    allowed_formats: set[str] | None = None,
) -> tuple[dict | None, str | None]:
    """
    Validates common report query parameters (`period`, `start_date`, `end_date`, `format`).

    Returns:
        (parsed_dict, None) on success
        (None, error_message) on validation failure
    """
    periods = allowed_periods or VALID_REPORT_PERIODS
    formats = allowed_formats or VALID_EXPORT_FORMATS

    period = request.query_params.get("period", "monthly").lower().strip()
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")

    if period not in periods:
        allowed_str = ", ".join(f"'{p}'" for p in sorted(periods))
        return None, f"Invalid period. Allowed values: {allowed_str}."

    if (start_date and not end_date) or (end_date and not start_date):
        return None, "Both 'start_date' and 'end_date' (YYYY-MM-DD) are required for custom filtering."

    if start_date and end_date:
        try:
            s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            if s_date > e_date:
                return None, "'start_date' cannot be after 'end_date'."
        except ValueError:
            return None, "Invalid date format. Expected YYYY-MM-DD."

    parsed = {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
    }

    if require_format:
        export_format = request.query_params.get("format", "xlsx").lower().strip()
        if export_format not in formats:
            allowed_fmt_str = ", ".join(f"'{f}'" for f in sorted(formats))
            return None, f"Invalid format. Supported values are {allowed_fmt_str}."
        parsed["format"] = export_format

    return parsed, None
