"""Exit codes and the error type the CLI turns into them."""

OK = 0
NO_HITS = 1
USAGE = 2
ASSET_NOT_FOUND = 3
INDEX_PROBLEM = 4
PAGE_NOT_FOUND = 5
NOT_INSTALLED = 6


class AppleDocError(Exception):
    """An expected failure: printed as one line on stderr, exits with ``code``."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code
