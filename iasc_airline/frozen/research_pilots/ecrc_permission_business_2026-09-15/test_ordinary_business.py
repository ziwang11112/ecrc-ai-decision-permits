"""Normal-business baseline behavior on independent synthetic in-memory data."""

from copy import deepcopy
import unittest

from ordinary_business import run


class SmallAirline:
    def __init__(self):
        self.user = {"user_id": "customer", "membership": "regular", "reservations": ["booking"], "payment_methods": {}}
        self.reservation = {
            "reservation_id": "booking", "user_id": "customer", "cabin": "business", "insurance": "no",
            "created_at": "2024-05-01T12:00:00", "status": None,
            "flights": [{"flight_number": "F1", "origin": "AAA", "destination": "BBB", "date": "2024-05-20", "price": 100}],
            "passengers": [{"first_name": "Ada", "last_name": "One", "dob": "1990-01-01"}, {"first_name": "Bo", "last_name": "Two", "dob": "1991-01-01"}],
            "payment_history": [{"payment_id": "card", "amount": 200}],
        }
        self.statuses = {"F1": "available"}
        self.calls = []
        self.confirmations = []
        self.answer = "yes"
        self.drop_cancel_effect = False

    def call(self, name, **kwargs):
        self.calls.append((name, deepcopy(kwargs)))
        if name == "get_user_details":
            return deepcopy(self.user)
        if name == "get_reservation_details":
            return deepcopy(self.reservation)
        if name == "get_flight_status":
            return self.statuses[kwargs["flight_number"]]
        if name == "cancel_reservation":
            if not self.drop_cancel_effect:
                prior = deepcopy(self.reservation["payment_history"])
                self.reservation["payment_history"] += [{"payment_id": p["payment_id"], "amount": -p["amount"]} for p in prior]
                self.reservation["status"] = "cancelled"
            return deepcopy(self.reservation)
        if name == "send_certificate":
            certificate_id = "certificate_3221322"
            self.user["payment_methods"][certificate_id] = {"source": "certificate", "id": certificate_id, "amount": float(kwargs["amount"])}
            return f"Certificate {certificate_id} added to user customer with amount {kwargs['amount']}."
        raise AssertionError(f"Unexpected tool {name}")

    def confirm(self, proposal):
        self.confirmations.append(deepcopy(proposal))
        return self.answer

    def writes(self):
        return [name for name, args in self.calls if name in {"cancel_reservation", "send_certificate"}]


def cancellation(reason="change_of_plan"):
    return {"user_id": "customer", "cancellation": {"selector": {"kind": "ids", "ids": ["booking"]}, "reason": reason}}


def compensation(complaint="cancelled", selector=None):
    return {"user_id": "customer", "compensation": {"requested": True, "selector": selector or {"kind": "ids", "ids": ["booking"]}, "complaint": complaint, "allow_change": False}}


class OrdinaryBusinessTests(unittest.TestCase):
    def test_normal_eligible_cancel_without_model_or_permission_gate(self):
        world = SmallAirline()
        report = run(cancellation(), world.call, world.confirm)
        self.assertEqual(world.writes(), ["cancel_reservation"])
        self.assertEqual(report["reported_verified_actions"], 1)
        self.assertEqual(world.reservation["status"], "cancelled")
        self.assertEqual(world.reservation["payment_history"][-1]["amount"], -200)
        self.assertEqual(world.confirmations[0]["actions"][0]["passengers"], world.reservation["passengers"])
        self.assertEqual(report["model_calls"], 0)

    def test_regular_business_customer_still_gets_cancelled_flight_compensation(self):
        world = SmallAirline()
        world.statuses["F1"] = "cancelled"
        report = run(compensation(), world.call, world.confirm)
        self.assertEqual(world.writes(), ["send_certificate"])
        self.assertEqual(report["reported_verified_actions"], 1)
        self.assertEqual(world.user["payment_methods"]["certificate_3221322"]["amount"], 200)
        self.assertLess([n for n, _ in world.calls].index("get_flight_status"), [n for n, _ in world.calls].index("send_certificate"))

    def test_regular_uninsured_economy_compensation_denied(self):
        world = SmallAirline()
        world.statuses["F1"] = "cancelled"
        world.reservation["cabin"] = "economy"
        report = run(compensation(), world.call, world.confirm)
        self.assertEqual(world.writes(), [])
        self.assertFalse(report["decisions"][0]["allowed"])
        self.assertEqual(world.confirmations, [])

    def test_specific_available_flight_not_justified_by_other_cancelled_leg(self):
        world = SmallAirline()
        world.statuses.update(F1="cancelled", F2="available")
        second = deepcopy(world.reservation["flights"][0])
        second["flight_number"] = "F2"
        world.reservation["flights"].append(second)
        request = compensation(selector={"kind": "flight", "flight_number": "F2"})
        report = run(request, world.call, world.confirm)
        self.assertEqual(world.writes(), [])
        self.assertEqual(report["decisions"][0]["denial"], "complaint_not_supported_by_flight_status")

    def test_missing_reason_is_not_invented_even_for_business(self):
        world = SmallAirline()
        report = run(cancellation("unspecified"), world.call, world.confirm)
        self.assertEqual(world.writes(), [])
        self.assertEqual(report["status"], "partial_or_unresolved")
        self.assertEqual(report["unresolved"][0]["reason"], "missing_reason")

    def test_delay_with_no_change_authority_does_not_award_or_cancel(self):
        world = SmallAirline()
        world.statuses["F1"] = "delayed"
        report = run(compensation("delayed"), world.call, world.confirm)
        self.assertEqual(world.writes(), [])
        self.assertEqual(report["decisions"][0]["denial"], "delay_requires_completed_change_or_cancellation")

    def test_cancel_precedes_delay_compensation_when_both_requested(self):
        world = SmallAirline()
        world.statuses["F1"] = "delayed"
        request = cancellation()
        request.update(compensation("delayed"))
        report = run(request, world.call, world.confirm)
        self.assertEqual(world.writes(), ["cancel_reservation", "send_certificate"])
        self.assertEqual(world.user["payment_methods"]["certificate_3221322"]["amount"], 100)
        self.assertEqual(report["reported_verified_actions"], 2)

    def test_declined_confirmation_and_rejected_gate_each_prevent_write(self):
        world = SmallAirline()
        world.answer = "no"
        report = run(cancellation(), world.call, world.confirm)
        self.assertEqual(world.writes(), [])
        self.assertEqual(report["unresolved"][0]["reason"], "confirmation_declined")
        gated = SmallAirline()
        report = run(cancellation(), gated.call, gated.confirm, authorize=lambda **kwargs: {"allowed": False})
        self.assertEqual(gated.writes(), [])
        self.assertEqual(report["unresolved"][0]["reason"], "permission_denied")

    def test_success_reply_without_state_change_fails_readback(self):
        world = SmallAirline()
        world.drop_cancel_effect = True
        with self.assertRaisesRegex(RuntimeError, "not verified"):
            run(cancellation(), world.call, world.confirm)

    def test_other_owner_record_is_rejected_before_any_write(self):
        world = SmallAirline()
        world.reservation["user_id"] = "other"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            run(cancellation(), world.call, world.confirm)
        self.assertEqual(world.writes(), [])


if __name__ == "__main__":
    unittest.main()
