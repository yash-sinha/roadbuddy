"""Tests for decision.py — pure functions, no mocking needed."""
import pytest
from backend.decision import get_action, get_nearest_garage, get_taxi, get_rental


class TestGetAction:
    def test_engine_failure_returns_tow(self):
        assert get_action("engine_failure") == "tow_truck"

    def test_accident_returns_tow(self):
        assert get_action("accident") == "tow_truck"

    def test_flat_tyre_returns_repair(self):
        assert get_action("flat_tyre") == "repair_truck"

    def test_flat_tyre_without_spare_returns_tow(self):
        assert get_action("flat_tyre", transcript="I have a flat tyre and no spare") == "tow_truck"

    def test_battery_returns_repair(self):
        assert get_action("battery") == "repair_truck"

    def test_severe_battery_returns_tow(self):
        assert get_action("battery", damage_severity="severe") == "tow_truck"

    def test_other_defaults_to_tow(self):
        assert get_action("other") == "tow_truck"

    def test_unknown_type_defaults_to_tow(self):
        assert get_action("unknown_garbage") == "tow_truck"


class TestGetNearestGarage:
    def test_returns_garage_dict_with_required_keys(self):
        garage = get_nearest_garage("SW1A 1AA", "tow_truck")
        assert "name" in garage
        assert "eta_minutes" in garage
        assert "distance_km" in garage
        assert "speciality" in garage

    def test_tow_returns_tow_capable_garage(self):
        garage = get_nearest_garage("SW1A 1AA", "tow_truck")
        assert garage["speciality"] in ("tow", "both")

    def test_repair_returns_repair_capable_garage(self):
        garage = get_nearest_garage("EC1A 1BB", "repair_truck")
        assert garage["speciality"] in ("repair", "both")

    def test_eta_is_positive(self):
        garage = get_nearest_garage("W1A 1AA", "tow_truck")
        assert garage["eta_minutes"] > 0

    def test_unknown_location_falls_back_to_central_london(self):
        garage = get_nearest_garage("somewhere random xyz", "tow_truck")
        assert garage["name"]  # still returns a garage


class TestGetTaxi:
    def test_returns_taxi_with_required_fields(self):
        taxi = get_taxi("SW1A 1AA")
        assert "name" in taxi
        assert "eta_minutes" in taxi
        assert "pickup" in taxi

    def test_eta_is_positive(self):
        taxi = get_taxi("EC1A 1BB")
        assert taxi["eta_minutes"] > 0


class TestGetRental:
    def test_severe_damage_returns_rental(self):
        rental = get_rental("severe")
        assert rental is not None
        assert "name" in rental

    def test_moderate_damage_returns_rental(self):
        rental = get_rental("moderate")
        assert rental is not None

    def test_minor_damage_returns_none(self):
        rental = get_rental("minor")
        assert rental is None
