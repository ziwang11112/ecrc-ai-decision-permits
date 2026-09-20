import copy
import unittest

from ordinary import _time_on_date, cancellation_eligibility, run


def reservation(rid="R-A", cabin="business", **changes):
    result = {
        "reservation_id": rid, "user_id": "customer", "cabin": cabin,
        "created_at": "2024-05-01T00:00:00", "insurance": "no",
        "passengers": [{"first_name": "Alex", "last_name": "Test", "dob": "1990-01-01"}],
        "flights": [{"flight_number": rid + "-F", "date": "2024-05-20", "origin": "AAA", "destination": "BBB", "price": 100}],
        "payment_history": [{"payment_id": "card", "amount": 100}],
        "status": None,
    }
    result.update(changes)
    return result


class FakeTools:
    def __init__(self, reservations):
        self.reservations = {item["reservation_id"]: copy.deepcopy(item) for item in reservations}
        self.calls = []
        self.statuses = {}
        self.schedules = {}
        self.fail_write = False
        self.no_effect = False

    def __call__(self, name, **kwargs):
        self.calls.append((name, copy.deepcopy(kwargs)))
        if name == "get_user_details":
            return {"user_id": "customer", "name": {"first_name": "Alex", "last_name": "Test"}, "dob": "1990-01-01", "reservations": list(self.reservations)}
        if name == "get_reservation_details":
            return copy.deepcopy(self.reservations[kwargs["reservation_id"]])
        if name == "get_flight_status":
            return self.statuses.get(kwargs["flight_number"], "available")
        if name == "cancel_reservation":
            if self.fail_write:
                raise TimeoutError("response unavailable")
            if not self.no_effect:
                target = self.reservations[kwargs["reservation_id"]]
                target["status"] = "cancelled"
                target["payment_history"].append({"payment_id": "card", "amount": -100})
            return copy.deepcopy(self.reservations[kwargs["reservation_id"]])
        if name == "list_all_airports":
            return [{"iata": "AAA", "city": "Origin"}, {"iata": "BBB", "city": "Destination"}, {"iata": "CCC", "city": "Elsewhere"}]
        if name == "search_direct_flight":
            result = []
            for item in self.reservations.values():
                for flight in item["flights"]:
                    if all(flight[key] == kwargs[key] for key in ("origin", "destination", "date")):
                        result.append({**flight, **self.schedules.get(flight["flight_number"], {"scheduled_departure_time_est": "10:00:00", "scheduled_arrival_time_est": "12:00:00"})})
            return list({item["flight_number"]: item for item in result}.values())
        raise AssertionError(name)


class OrdinaryTests(unittest.TestCase):
    def request(self, **changes):
        value = {"mode": "cancel_upcoming", "user_id": "customer", "reason": "other"}
        value.update(changes)
        return value

    def test_future_business_selected_economy_insurance_only_preserved(self):
        tools = FakeTools([reservation("R-A"), reservation("R-B", "economy", insurance="yes")])
        before = copy.deepcopy(tools.reservations["R-B"])
        report = run(self.request(), tools, lambda proposal: "yes")
        self.assertEqual([item["reservation_id"] for item in report["actions"]], ["R-A"])
        self.assertEqual(tools.reservations["R-B"], before)
        self.assertEqual(report["model_calls"], 0)

    def test_ids_and_database_order_do_not_select_target(self):
        tools = FakeTools([reservation("random-other", "economy"), reservation("renamed-business")])
        report = run(self.request(), tools, lambda proposal: "yes")
        self.assertEqual([item["reservation_id"] for item in report["actions"]], ["renamed-business"])

    def test_already_flown_overrides_business_and_cancelled_other_leg(self):
        value = reservation(flights=[{}, {}])
        rule = cancellation_eligibility(value, ["landed", "cancelled"], "other")
        self.assertFalse(rule["allowed"])
        self.assertEqual(rule["reason"], "portion_already_flown_transfer_required")

    def test_partial_trip_with_future_leg_not_cancelled(self):
        value = reservation(flights=[{"flight_number": "PAST", "date": "2024-05-10"}, {"flight_number": "FUTURE", "date": "2024-05-20"}])
        tools = FakeTools([value]); tools.statuses["PAST"] = "landed"
        report = run(self.request(), tools, lambda proposal: self.fail("Must not propose"))
        self.assertEqual(report["status"], "needs_clarification")
        self.assertFalse(report["actions"])

    def test_past_flights_outside_upcoming_scope_preserved(self):
        value = reservation(flights=[{"flight_number": "PAST", "date": "2024-05-10"}])
        tools = FakeTools([value]); tools.statuses["PAST"] = "landed"
        before = copy.deepcopy(tools.reservations)
        report = run(self.request(), tools, lambda proposal: self.fail("Must not propose"))
        self.assertEqual(tools.reservations, before)
        self.assertEqual(report["status"], "completed_no_write")

    def test_health_insurance_and_booking_window(self):
        value = reservation(cabin="economy", insurance="yes")
        self.assertTrue(cancellation_eligibility(value, ["available"], "health")["allowed"])
        value["insurance"] = "no"
        value["created_at"] = "2024-05-14T15:00:00"
        self.assertTrue(cancellation_eligibility(value, ["available"], "other")["allowed"])
        value["created_at"] = "2024-05-14T14:59:59"
        self.assertFalse(cancellation_eligibility(value, ["available"], "other")["allowed"])

    def test_airline_cancellation_is_native_status_not_user_assertion(self):
        value = reservation(cabin="economy")
        self.assertFalse(cancellation_eligibility(value, ["available"], "airline_cancelled")["allowed"])
        self.assertTrue(cancellation_eligibility(value, ["cancelled"], "other")["allowed"])

    def test_unknown_status_and_already_cancelled_preserved(self):
        self.assertFalse(cancellation_eligibility(reservation(), ["unknown"], "other")["allowed"])
        self.assertFalse(cancellation_eligibility(reservation(status="cancelled"), ["available"], "other")["allowed"])

    def test_explicit_confirmation_precedes_write_and_lists_full_scope(self):
        tools = FakeTools([reservation()])
        def confirm(proposal):
            self.assertFalse(any(name == "cancel_reservation" for name, _ in tools.calls))
            self.assertEqual(proposal["actions"][0]["scope"], "whole_reservation")
            self.assertEqual(len(proposal["actions"][0]["passengers"]), 1)
            return "yes"
        report = run(self.request(), tools, confirm)
        confirmation = next(item["sequence"] for item in report["trace"] if item["kind"] == "scripted_user_confirmation")
        write = next(item["sequence"] for item in report["trace"] if item["kind"] == "tool_call" and item["name"] == "cancel_reservation")
        self.assertLess(confirmation, write)

    def test_boolean_confirmation_is_not_explicit_yes(self):
        tools = FakeTools([reservation()])
        report = run(self.request(), tools, lambda proposal: True)
        self.assertEqual(report["status"], "confirmation_declined")
        self.assertFalse(any(name == "cancel_reservation" for name, _ in tools.calls))

    def test_write_timeout_not_retried_and_no_completion_claim(self):
        tools = FakeTools([reservation(), reservation("R-B")]); tools.fail_write = True
        report = run(self.request(), tools, lambda proposal: "yes")
        self.assertEqual(report["status"], "tool_or_data_error")
        self.assertEqual(sum(name == "cancel_reservation" for name, _ in tools.calls), 1)
        self.assertFalse(any(item["status"] == "cancelled_verified" for item in report["actions"]))

    def test_success_return_without_state_change_is_failure(self):
        tools = FakeTools([reservation()]); tools.no_effect = True
        report = run(self.request(), tools, lambda proposal: "yes")
        self.assertEqual(report["status"], "verification_failed")

    def test_ownership_mismatch_stops_before_writes(self):
        tools = FakeTools([reservation(user_id="different-customer")])
        report = run(self.request(), tools, lambda proposal: self.fail("Must not propose"))
        self.assertEqual(report["status"], "tool_or_data_error")
        self.assertFalse(any(name == "cancel_reservation" for name, _ in tools.calls))

    def test_itinerary_anchor_overlap_preserves_other_passenger(self):
        anchor = reservation("ANCHOR")
        overlap = reservation("OVERLAP", flights=[{"flight_number": "OVERLAP-F", "date": "2024-05-20", "origin": "CCC", "destination": "BBB"}])
        other = copy.deepcopy(overlap); other["reservation_id"] = "OTHER"; other["passengers"][0]["first_name"] = "Somebody"
        tools = FakeTools([anchor, overlap, other])
        request = self.request(mode="resolve_itinerary_conflicts", anchors=[{"event": "departure", "date": "2024-05-20", "origin": "Origin"}], preserve_other_passengers=True)
        report = run(request, tools, lambda proposal: "yes")
        self.assertEqual([item["reservation_id"] for item in report["actions"]], ["OVERLAP"])
        self.assertIsNone(tools.reservations["ANCHOR"]["status"])
        self.assertIsNone(tools.reservations["OTHER"]["status"])

    def test_public_airport_alias_can_match_existing_trip(self):
        tools = FakeTools([reservation()])
        request = self.request(mode="resolve_itinerary_conflicts", anchors=[{"event": "arrival", "date": "2024-05-20", "destination": "Metro"}], public_context={"city_airports": {"Metro": ["BBB"]}})
        report = run(request, tools, lambda proposal: self.fail("Anchor alone is preserved"))
        self.assertEqual(report["itinerary_analysis"]["protected_reservations"], ["R-A"])
        self.assertFalse(report["unresolved"])

    def test_two_possible_anchors_are_not_arbitrarily_chosen(self):
        tools = FakeTools([reservation("A"), reservation("B")])
        request = self.request(mode="resolve_itinerary_conflicts", anchors=[{"event": "departure", "date": "2024-05-20", "origin": "Origin"}])
        report = run(request, tools, lambda proposal: self.fail("Must clarify"))
        self.assertEqual(report["status"], "needs_clarification")
        self.assertFalse(report["actions"])

    def test_nonoverlapping_earlier_trip_needs_preference_not_cancellation(self):
        tools = FakeTools([reservation("ANCHOR"), reservation("EARLIER", flights=[{"flight_number": "EARLIER-F", "date": "2024-05-19", "origin": "CCC", "destination": "BBB"}])])
        request = self.request(mode="resolve_itinerary_conflicts", anchors=[{"event": "departure", "date": "2024-05-20", "origin": "Origin"}])
        report = run(request, tools, lambda proposal: self.fail("Must clarify"))
        self.assertEqual(report["status"], "needs_clarification")
        self.assertFalse(report["actions"])

    def test_overnight_schedule(self):
        self.assertEqual(_time_on_date("2024-05-20", "02:00:00+1").isoformat(), "2024-05-21T02:00:00")


if __name__ == "__main__":
    unittest.main()
