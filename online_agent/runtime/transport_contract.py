"""Public exception boundary for a caller-supplied model transport.

This module does not load credentials, make requests, or implement monetary
accounting. These exception names replace the original private accounting
module's exceptions; the actor loop otherwise retains its original behavior.
"""


class BudgetDenied(RuntimeError):
    """The caller declined a model call before dispatch."""


class ProviderFailure(RuntimeError):
    """A call cannot supply dispatchable output; never automatically retry.

    Optional attributes consumed by trajectory.run_episode: category, stage,
    and call_id. Allowed categories are documented in that module's
    STOP_STATUSES; other categories are recorded as provider_failure.
    """
