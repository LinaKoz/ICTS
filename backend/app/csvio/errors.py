"""CSV-specific error codes (§6, P14). All use the one error shape of
`app.errors`; they only add codes to existing status families."""
from __future__ import annotations

from app.errors import BadRequestError


class MissingColumnsError(BadRequestError):
    code = "MISSING_COLUMNS"


class DuplicateColumnError(BadRequestError):
    code = "DUPLICATE_COLUMN"


class InvalidEncodingError(BadRequestError):
    code = "INVALID_ENCODING"


class EmptyFileError(BadRequestError):
    code = "EMPTY_FILE"
