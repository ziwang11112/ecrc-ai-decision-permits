"""Synthetic public-selector tests; no native business episodes or writes."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import selector_adapter


def request(selector, reason="unspecified"):
    return {"user_id": "customer", "user_statement": "Please cancel the selected booking.",
            "cancellation": {"selector": deepcopy(selector), "reason": reason}}


class NativeReads:
    def __init__(self):
        self.user = {"user_id": "customer", "reservations": ["native-one", "native-two", "past"]}
        self.reservations = {}
        for rid, origin, destination, date, passenger_count, insured in (
            ("native-one", "AAA", "BBB", "2024-05-20", 1, "no"),
            ("native-two", "CCC", "DDD", "2024-05-21", 2, "yes"),
            ("past", "EEE", "FFF", "2024-05-01", 1, "no"),
        ):
            self.reservations[rid] = {"reservation_id": rid, "user_id": "customer", "status": None,
                                      "flights": [{"flight_number": "F-" + rid, "origin": origin,
                                                   "destination": destination, "date": date}],
                                      "passengers": [{"name": str(i)} for i in range(passenger_count)],
                                      "cabin": "economy", "insurance": insured,
                                      "created_at": "2024-05-01T12:00:00"}
        self.calls = []

    def __call__(self, name, **arguments):
        self.calls.append({"name": name, "arguments": deepcopy(arguments)})
        if name == "get_user_details":
            return deepcopy(self.user)
        if name == "get_reservation_details":
            return deepcopy(self.reservations[arguments["reservation_id"]])
        raise AssertionError("resolver attempted non-object read or write: " + name)


class SelectorAdapterTests(unittest.TestCase):
    def test_flight_selector_gets_id_from_native_facts_and_preserves_request(self):
        world = NativeReads()
        original = request({"kind": "flight", "origin": "CCC", "destination": "DDD"})
        before = deepcopy(original)
        result = selector_adapter.resolve(original, world)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected_ids"], ["native-two"])
        self.assertNotIn("native-two", str(original))
        self.assertEqual(original, before)
        self.assertEqual(result["original_request"], original)
        self.assertEqual(result["resolved_request"]["cancellation"]["selector"], {"kind": "ids", "ids": ["native-two"]})
        self.assertEqual(result["resolved_request"]["cancellation"]["reason"], "unspecified")
        self.assertEqual(len(world.calls), 4)
        self.assertEqual(result["resolution_records"][2]["response"]["reservation_id"], "native-two")

    def test_reservation_route_resolves_connecting_trip_without_matching_single_leg(self):
        world = NativeReads()
        selected = world.reservations["native-two"]
        selected.update(origin="AAA", destination="DDD")
        selected["flights"] = [
            {"flight_number": "OUT1", "origin": "AAA", "destination": "MID", "date": "2024-05-21"},
            {"flight_number": "OUT2", "origin": "MID", "destination": "DDD", "date": "2024-05-21"},
            {"flight_number": "BACK", "origin": "DDD", "destination": "AAA", "date": "2024-05-25"},
        ]
        original = request({"kind": "reservation_route", "origin": "AAA", "destination": "DDD"})
        self.assertNotIn("native-two", str(original))
        with patch.object(selector_adapter.ORDINARY, "cancel_basis", side_effect=AssertionError("must not qualify")):
            result = selector_adapter.resolve(original, world)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected_ids"], ["native-two"])
        self.assertEqual(result["original_request"], original)
        self.assertEqual(result["resolved_request"]["cancellation"]["reason"], "unspecified")
        self.assertEqual(result["resolved_request"]["cancellation"]["selector"], {"kind": "ids", "ids": ["native-two"]})
        self.assertEqual(len(world.calls), 4)
        self.assertEqual(result["resolution_records"][-2]["route_match_ids"], ["native-two"])
        self.assertFalse(result["eligibility_evaluated"])

    def test_multiple_reservations_with_route_are_ambiguous_before_passenger_filter(self):
        world = NativeReads()
        for rid in ("native-one", "native-two"):
            world.reservations[rid].update(origin="AAA", destination="DDD")
        result = selector_adapter.resolve(request({"kind": "reservation_route", "origin": "AAA",
                                                  "destination": "DDD", "passenger_count": 1}), world)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason"], "ambiguous_reservation_route")
        self.assertEqual(result["selected_ids"], [])
        self.assertIsNone(result["resolved_request"])
        self.assertEqual(result["resolution_records"][-1]["route_match_ids"], ["native-one", "native-two"])

    def test_reservation_route_does_not_infer_endpoints_from_single_leg(self):
        world = NativeReads()
        world.reservations["native-one"].update(origin="AAA", destination="ELSEWHERE")
        result = selector_adapter.resolve(request({"kind": "reservation_route", "origin": "AAA", "destination": "BBB"}), world)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason"], "no_candidate")

    def test_unique_reservation_route_applies_requested_passenger_count(self):
        world = NativeReads()
        world.reservations["native-two"].update(origin="CCC", destination="DDD")
        selector = {"kind": "reservation_route", "origin": "CCC", "destination": "DDD", "passenger_count": 2}
        result = selector_adapter.resolve(request(selector), world)
        self.assertEqual(result["selected_ids"], ["native-two"])
        selector["passenger_count"] = 1
        empty = selector_adapter.resolve(request(selector), world)
        self.assertEqual(empty["status"], "unresolved")
        self.assertEqual(empty["reason"], "no_candidate")

    def test_reservation_route_requires_both_endpoints_and_rejects_extra_scope(self):
        for selector, reason in (
            ({"kind": "reservation_route", "origin": "AAA"}, "reservation_route_requires_both_endpoints"),
            ({"kind": "reservation_route", "origin": "AAA", "destination": ""}, "invalid_reservation_route_endpoint"),
            ({"kind": "reservation_route", "origin": "AAA", "destination": "BBB", "flight_type": "round_trip"},
             "unsupported_selector_qualifier"),
        ):
            with self.subTest(selector=selector):
                result = selector_adapter.resolve(request(selector), NativeReads())
                self.assertEqual(result["status"], "unresolved")
                self.assertEqual(result["reason"], reason)

    def test_selection_never_filters_by_cancellation_eligibility(self):
        world = NativeReads()
        with patch.object(selector_adapter.ORDINARY, "cancel_basis", side_effect=AssertionError("must not qualify")):
            result = selector_adapter.resolve(request({"kind": "all_upcoming"}, "health"), world)
        self.assertEqual(result["selected_ids"], ["native-one", "native-two"])
        self.assertFalse(result["eligibility_evaluated"])
        self.assertTrue(all(call["name"] in {"get_user_details", "get_reservation_details"} for call in world.calls))

    def test_one_passenger_scope_is_applied_without_inventing_reason(self):
        result = selector_adapter.resolve(request({"kind": "all_upcoming", "passenger_count": 1}), NativeReads())
        self.assertEqual(result["selected_ids"], ["native-one"])
        self.assertEqual(result["resolved_request"]["cancellation"]["reason"], "unspecified")
        self.assertEqual(result["original_request"]["cancellation"]["selector"]["passenger_count"], 1)

    def test_ambiguous_flight_is_not_disambiguated_by_passenger_count(self):
        world = NativeReads()
        world.reservations["native-two"]["flights"] = deepcopy(world.reservations["native-one"]["flights"])
        result = selector_adapter.resolve(request({"kind": "flight", "origin": "AAA", "passenger_count": 1}), world)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason"], "ambiguous_or_unmatched_flight_selector")
        self.assertIsNone(result["resolved_request"])

    def test_unknown_explicit_id_is_not_dropped_to_leave_a_successful_subset(self):
        result = selector_adapter.resolve(request({"kind": "ids", "ids": ["native-one", "unknown"]}), NativeReads())
        self.assertEqual(result["reason"], "unknown_or_unowned_selected_reservation")
        self.assertEqual(result["selected_ids"], [])
        self.assertIsNone(result["resolved_request"])

    def test_invalid_passenger_counts_are_unresolved(self):
        for count in (True, False, 0, -1, 1.5, "1", None):
            with self.subTest(count=count):
                result = selector_adapter.resolve(request({"kind": "all_upcoming", "passenger_count": count}), NativeReads())
                self.assertEqual(result["reason"], "invalid_passenger_count")
                self.assertEqual(result["status"], "unresolved")

    def test_zero_matches_are_unresolved_not_vacuous_completion(self):
        for selector in ({"kind": "ids", "ids": []}, {"kind": "all_upcoming", "passenger_count": 3}):
            with self.subTest(selector=selector):
                result = selector_adapter.resolve(request(selector), NativeReads())
                self.assertEqual(result["reason"], "no_candidate")
                self.assertIsNone(result["resolved_request"])

    def test_missing_duplicate_ids_and_missing_flight_fields_are_not_guessed(self):
        for selector, reason in (
            ({"kind": "ids"}, "missing_or_malformed_reservation_ids"),
            ({"kind": "ids", "ids": ["native-one", "native-one"]}, "duplicate_reservation_ids"),
            ({"kind": "flight"}, "flight_selector_without_identifying_fields"),
            ({"kind": "flight", "origin": ""}, "invalid_flight_selector_field"),
        ):
            with self.subTest(selector=selector):
                result = selector_adapter.resolve(request(selector), NativeReads())
                self.assertEqual(result["reason"], reason)

    def test_itinerary_conflict_and_unknown_qualifiers_remain_unresolved(self):
        for selector, reason in (
            ({"kind": "itinerary_conflict"}, "unsupported_itinerary_conflict_selector"),
            ({"kind": "all_upcoming", "minimum_duration": 120}, "unsupported_selector_qualifier"),
        ):
            with self.subTest(selector=selector):
                result = selector_adapter.resolve(request(selector), NativeReads())
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["resolved_request"])

    def test_account_or_reservation_ownership_mismatch_is_retained_failure(self):
        world = NativeReads()
        world.reservations["native-two"]["user_id"] = "someone-else"
        result = selector_adapter.resolve(request({"kind": "ids", "ids": ["native-one"]}), world)
        self.assertEqual(result["reason"], "reservation_identity_or_ownership_mismatch")
        self.assertEqual(result["status"], "unresolved")

    def test_native_query_failure_is_not_relabelled_business_ineligibility(self):
        def unavailable(name, **arguments):
            raise RuntimeError("fixture unavailable")
        result = selector_adapter.resolve(request({"kind": "all_upcoming"}), unavailable)
        self.assertEqual(result["reason"], "native_account_query_failed")
        self.assertEqual(result["resolution_records"][0]["error"]["type"], "RuntimeError")

    def test_dependencies_unchanged_and_derived_shape_works_with_frozen_actor(self):
        before = selector_adapter.source_manifest()
        result = selector_adapter.resolve(request({"kind": "ids", "ids": ["native-two"]}), NativeReads())
        self.assertEqual(set(result["resolved_request"]), {"user_id", "user_statement", "cancellation"})
        self.assertEqual(selector_adapter.source_manifest(), before)
        self.assertEqual(len(selector_adapter.dependency_files()), 2)


if __name__ == "__main__":
    unittest.main()
