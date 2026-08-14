"""Typed failures for fail-closed ECRC governance operations."""


class GovernanceError(RuntimeError):
    """Base class for governance failures."""


class PolicyNotRegisteredError(GovernanceError):
    pass


class StalePolicyError(GovernanceError):
    pass


class RevokedPolicyError(GovernanceError):
    pass


class PolicyNotYetEffectiveError(GovernanceError):
    pass


class PolicyExpiredError(GovernanceError):
    pass


class CapacityExceededError(GovernanceError):
    pass


class IdempotencyConflictError(GovernanceError):
    pass


class ReservationStateError(GovernanceError):
    pass


class InvalidPermitError(GovernanceError):
    pass


class PermitReplayError(GovernanceError):
    pass


class ReceiptVerificationError(GovernanceError):
    pass
