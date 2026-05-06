"""Canonical path-parameter types for FastAPI routers.

Use these annotations on path-param function arguments to let FastAPI /
Pydantic validate format before the handler runs. Validation errors
automatically return 422 with a clear detail body — no manual regex guards
needed in the handler.
"""

import re
from typing import Annotated

from pydantic import StringConstraints


# KSeF invoice number: NIP(10) - date(8) - random(>=6 alnum upper) - check(2 alnum upper)
KSEF_NUMBER_REGEX = r"^\d{10}-\d{8}-[A-Z0-9]{6,}-[A-Z0-9]{2}$"

# Compiled form for imperative callers (e.g. ksef_client._validate_ksef_number).
KSEF_NUMBER_PATTERN = re.compile(KSEF_NUMBER_REGEX)

# FastAPI / Pydantic path-parameter type: constrains input via regex at parse time.
KsefNumberPath = Annotated[
    str,
    StringConstraints(pattern=KSEF_NUMBER_REGEX, min_length=28, max_length=80),
]
