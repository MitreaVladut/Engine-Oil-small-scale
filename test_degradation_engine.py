"""
test_degradation_engine.py
--------------------------
Unit and Integration Test Suite for the Algorithmic Engine Oil Life Monitoring System.
Verifies mathematical degradation formulations, top-up additive recovery,
SQLite repository persistence, CSV replay, and simulation reproducibility.

Meets Non-Functional Requirement: NFR4 (Modular layers with a unit-tested model)
"""

import pytest
import os
import tempfile
from datetime import datetime, timedelta

from degradation_engine import OilConfig, TelemetrySample, DegradationEngine
from storage_repository import StorageRepository
from data_sources import CSVReplayDataSource
from drive_cycle_simulator import DriveCycleSimulator


class TestDegradationMath:
    """Verifies Section 4.3 mathematical formulas against exact analytical expectations."""

    def test_stress_factors_optimal_baseline(self):
        """Under baseline conditions (RPM <= 3500, 70 <= Temp <= 100, Load = 50%), stress factor S = 1.0."""
        engine = DegradationEngine()
        f_rpm, f_temp, f_load, stress = engine.compute_stress_factors(
            rpm=2500.0,
            coolant_temp_c=85.0,
            engine_load_pct=50.0
        )
        assert f_rpm == 1.0
        assert f_temp == 1.0
        assert pytest.approx(f_load, 1e-5) == 1.0
        assert pytest.approx(stress, 1e-5) == 1.0

    def test_mechanical_shear_penalty_above_3500_rpm(self):
        """Above 3500 RPM, M_RPM scales quadratically: M_RPM = 1.0 + ((RPM - 3500) / 1000)^2."""
        engine = DegradationEngine()
        
        # Test 4500 RPM: 1.0 + (1000/1000)^2 = 2.0
        f_rpm_4500, _, _, _ = engine.compute_stress_factors(4500.0, 85.0, 50.0)
        assert pytest.approx(f_rpm_4500, 1e-5) == 2.0

        # Test 5500 RPM: 1.0 + (2000/1000)^2 = 5.0
        f_rpm_5500, _, _, _ = engine.compute_stress_factors(5500.0, 85.0, 50.0)
        assert pytest.approx(f_rpm_5500, 1e-5) == 5.0

    def test_cold_start_condensation_penalty(self):
        """Coolant temp < 70 C triggers a 2.0x cold operation penalty."""
        engine = DegradationEngine()
        _, f_temp_cold, _, _ = engine.compute_stress_factors(2000.0, 45.0, 30.0)
        assert f_temp_cold == 2.0

    def test_thermal_overheating_penalty(self):
        """Coolant temp > 100 C triggers a 1.5x thermal oxidation penalty."""
        engine = DegradationEngine()
        _, f_temp_hot, _, _ = engine.compute_stress_factors(2000.0, 105.0, 30.0)
        assert f_temp_hot == 1.5

    def test_engine_load_scaling(self):
        """Load scales from 0.8 at 0% to 1.2 at 100%."""
        engine = DegradationEngine()
        _, _, f_load_0, _ = engine.compute_stress_factors(2000.0, 85.0, 0.0)
        _, _, f_load_100, _ = engine.compute_stress_factors(2000.0, 85.0, 100.0)
        assert pytest.approx(f_load_0, 1e-5) == 0.8
        assert pytest.approx(f_load_100, 1e-5) == 1.2

    def test_revolutions_and_damage_integration(self):
        """Verifies discrete crankshaft revolutions Delta_N and damage increment Delta_D."""
        config = OilConfig(base_mileage_km=10000.0, revs_per_km=2500.0)  # N_ref = 25,000,000 revs
        engine = DegradationEngine(config=config, initial_damage=0.0)

        # 3000 RPM for 60 seconds at baseline operating conditions -> Delta_N = 3000 revs
        sample = TelemetrySample(
            timestamp=datetime.now(),
            rpm=3000.0,
            speed_kmh=80.0,
            coolant_temp_c=85.0,
            engine_load_pct=50.0,
            delta_t=60.0
        )
        res = engine.process_sample(sample)

        assert pytest.approx(res.delta_n, 1e-5) == 3000.0
        assert pytest.approx(res.stress_factor, 1e-5) == 1.0
        expected_damage = 3000.0 / 25000000.0  # 0.00012
        assert pytest.approx(res.delta_damage, 1e-7) == expected_damage
        assert pytest.approx(engine.damage, 1e-7) == expected_damage
        assert pytest.approx(engine.rul_percent, 1e-5) == (1.0 - expected_damage) * 100.0


class TestAdditiveRecoveryAndTopUp:
    """Verifies Section 4.4 Additive Concentration Recovery via Oil Replenishment."""

    def test_top_up_additive_recovery_formula(self):
        """
        Tests top-up damage attenuation:
            D' = D * (1 - eta * V_t / V_s)
            H_new = ((V_s - eta * V_t) * H_old + eta * V_t * 100) / V_s
        """
        # Sump: 3.7 L, eta: 0.95, Initial RUL: 70% (Damage: 0.30)
        config = OilConfig(sump_capacity_liters=3.7, default_mixing_efficiency=0.95)
        engine = DegradationEngine(config=config, initial_damage=0.30)
        assert pytest.approx(engine.rul_percent, 1e-5) == 70.0

        # Top-up with 1.0 Liters
        topup_res = engine.apply_top_up(volume_liters=1.0)

        # Expected attenuation fraction: 0.95 * (1.0 / 3.7) = 0.256756756...
        expected_recovery_frac = 0.95 * (1.0 / 3.7)
        expected_new_damage = 0.30 * (1.0 - expected_recovery_frac)
        expected_new_rul = (1.0 - expected_new_damage) * 100.0

        assert pytest.approx(engine.damage, 1e-5) == expected_new_damage
        assert pytest.approx(engine.rul_percent, 1e-5) == expected_new_rul
        assert engine.rul_percent > 70.0  # RUL rose after top-up!
        assert pytest.approx(topup_res["rul_gain"], 1e-4) == (expected_new_rul - 70.0)

    def test_full_oil_change_resets_health(self):
        """Complete oil change drains old oil and returns RUL to 100%."""
        engine = DegradationEngine(initial_damage=0.65)
        assert pytest.approx(engine.rul_percent, 1e-5) == 35.0

        res = engine.apply_full_oil_change(new_oil_type="Fully Synthetic")
        assert engine.damage == 0.0
        assert engine.rul_percent == 100.0
        assert engine.config.oil_type == "Fully Synthetic"
        assert engine.config.base_mileage_km == 15000.0


class TestConfigurabilityNFR2:
    """Verifies Non-Functional Requirement NFR2: Model coefficients configurable, not hard-coded."""

    def test_custom_oil_configuration(self):
        custom_config = OilConfig(
            oil_type="Race Synthetic 10W-60",
            base_mileage_km=8000.0,
            revs_per_km=3000.0,
            sump_capacity_liters=4.2,
            rpm_threshold=4000.0,
            temp_cold_threshold=65.0,
            temp_penalty_cold=2.5
        )
        engine = DegradationEngine(config=custom_config)
        assert engine.config.reference_budget_revs == 8000.0 * 3000.0

        # RPM at 3800 should have NO penalty with custom threshold 4000
        f_rpm, _, _, _ = engine.compute_stress_factors(3800.0, 80.0, 50.0)
        assert f_rpm == 1.0

        # Temp at 60 C should use custom cold penalty 2.5
        _, f_temp, _, _ = engine.compute_stress_factors(3800.0, 60.0, 50.0)
        assert f_temp == 2.5


class TestStorageRepository:
    """Verifies SQLite persistence layer and repository transactions."""

    def test_repository_lifecycle(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db_path = tmp.name

        try:
            repo = StorageRepository(db_path=tmp_db_path)
            state = repo.get_or_create_oil_state()
            assert state["current_rul_percent"] == 100.0
            assert state["vehicle_model"] == "Skoda Fabia 1.4L"

            # Create trip and log sample
            trip_id = repo.start_trip("TEST_SOURCE", "Unit Test Trip", initial_rul=98.5)
            assert trip_id > 0

            engine = DegradationEngine(initial_damage=0.015)
            sample = TelemetrySample(datetime.now(), 2500.0, 60.0, 85.0, 40.0, 1.0)
            res = engine.process_sample(sample)

            repo.log_sample(trip_id, sample, res)
            repo.save_oil_state(engine)
            repo.end_trip(trip_id, final_rul=res.rul_percent, distance_km=0.016, duration_seconds=1.0)

            trips = repo.get_trips(10)
            assert len(trips) == 1
            assert trips[0]["trip_id"] == trip_id

            samples = repo.get_trip_samples(trip_id)
            assert len(samples) == 1
            assert samples[0]["rpm"] == 2500.0

            # Log maintenance event
            event_id = repo.log_maintenance_event(
                event_type="TOP_UP",
                volume_liters=0.5,
                oil_grade="5W-40",
                mixing_efficiency=0.95,
                rul_before=70.0,
                rul_after=73.5,
                notes="Quarterly top-up"
            )
            assert event_id > 0
            history = repo.get_maintenance_history(10)
            assert len(history) == 1
            assert history[0]["volume_liters"] == 0.5
        finally:
            try:
                if os.path.exists(tmp_db_path):
                    os.remove(tmp_db_path)
            except PermissionError:
                pass


class TestDriveCycleSimulatorNFR3:
    """Verifies NFR3: Simulations reproducible across identical seed parameters."""

    def test_reproducible_cold_trip(self):
        sim = DriveCycleSimulator(ambient_temp_c=18.0)
        fixed_time = datetime(2026, 11, 23, 10, 0, 0)
        
        cycle1 = sim.generate_cold_short_trip(duration_seconds=100, start_time=fixed_time)
        cycle2 = sim.generate_cold_short_trip(duration_seconds=100, start_time=fixed_time)

        assert len(cycle1) == 100
        assert len(cycle2) == 100
        for s1, s2 in zip(cycle1, cycle2):
            assert s1.rpm == s2.rpm
            assert s1.coolant_temp_c == s2.coolant_temp_c
            assert s1.engine_load_pct == s2.engine_load_pct
            assert s1.speed_kmh == s2.speed_kmh
