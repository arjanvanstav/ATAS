"""
exceptions.py — Custom exceptions for the ATAS package.
"""


class Initializing_error(Exception):
    """Raised when a simulation is called before the required setup (e.g. set_city) is done."""
    def __init__(self, message) -> None:
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return str(self.message)
