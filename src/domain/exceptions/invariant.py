"""Domain invariant violation."""


class InvariantViolation(RuntimeError):
    """Raised when a domain invariant is violated.

    Use this for conditions that should be impossible if upstream code is
    correct (e.g. an AUTONOMOUS conversation lacking a coordinator). The
    application layer should treat this as a bug-class signal rather than
    routine input validation.
    """
