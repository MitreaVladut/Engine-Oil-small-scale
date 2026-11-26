"""
test_rapid_oil_drain.py
-----------------------
Extreme Torture & Accelerated Degradation Test File.
Simulates physically extreme, hypothetical engine stress conditions
(e.g. 24,000 RPM dyno redline, 138 °C coolant boiling, 100% continuous torque load)
designed to rapidly drain oil life (RUL %) from 100% to 0.0% in seconds.

Can be executed directly:
    python test_rapid_oil_drain.py
Or as part of pytest:
    python -m pytest test_rapid_oil_drain.py -v
"""

import os
import sys
import time
import pytest
from datetime import datetime

from degradation_engine import OilConfig, TelemetrySample, DegradationEngine
from storage_repository import StorageRepository
from drive_cycle_simulator import DriveCycleSimulator


def run_rapid_oil_drain_simulation(
    target_drain_seconds: int = 40,
    rpm_torture: float = 24000.0,
    temp_torture: float = 138.0,
    load_torture: float = 100.0,
    db_path: str = "oil_monitor.db",
    export_csv: str = "rapid_oil_drain_log.csv",
    verbose: bool = True
) -> dict:
    """
    Executes the extreme stress cycle, draining oil life from 100% down to 0%.
    """
    if verbose:
        print("\n" + "=" * 78)
        print("  🔥 CATASTROPHIC ENGINE STRESS TEST - RAPID OIL LIFE DRAIN 🔥")
        print("=" * 78)
        print("  Testing extreme operating parameters far beyond real-car physical limits:")
        print(f"  • Engine Speed:       {rpm_torture:,.0f} RPM (Extreme Dyno Overspeed)")
        print(f"  • Coolant Temp:       {temp_torture:.1f} °C (Severe Overheating / Boiling)")
        print(f"  • Engine Load:        {load_torture:.1f}% (Wide Open Throttle)")
        print(f"  • Base Oil Grade:     Mineral 5,000 km (for rapid thermal breakdown)")
        print("-" * 78)

    # Initialize repository and engine
    repo = StorageRepository(db_path=db_path)
    config = OilConfig(
        oil_type="Mineral",
        base_mileage_km=5000.0,            # 5000 km reference budget
        sump_capacity_liters=3.7,
        rpm_threshold=3500.0,
        temp_hot_threshold=100.0,
        temp_penalty_hot=1.5,
        load_base_multiplier=0.8,
        load_slope_multiplier=0.4
    )
    engine = DegradationEngine(config=config, initial_damage=0.0)

    # Generate the extreme torture samples
    sim = DriveCycleSimulator()
    samples = sim.generate_catastrophic_torture_cycle(
        duration_seconds=target_drain_seconds,
        rpm_target=rpm_torture,
        coolant_temp_target=temp_torture,
        load_target=load_torture,
        delta_t_step=1.0
    )

    # Start trip in SQLite
    trip_id = repo.start_trip(
        source_type="EXTREME_TORTURE",
        scenario_name="Rapid Oil Life Drain (24,000 RPM Torture Test)",
        initial_rul=100.0
    )

    if verbose:
        print(f"{'Time':<6} | {'RPM':<9} | {'Temp (°C)':<10} | {'Stress (S)':<11} | {'Damage (D)':<12} | {'RUL (%)':<9} | {'Alert Status'}")
        print("-" * 78)

    history = []
    alert_transitions = []
    prior_alert = engine.alert_level

    for i, s in enumerate(samples):
        res = engine.process_sample(s)
        repo.log_sample(trip_id, s, res)
        history.append({
            "step": i + 1,
            "rpm": s.rpm,
            "temp": s.coolant_temp_c,
            "stress": res.stress_factor,
            "damage": res.cumulative_damage,
            "rul": res.rul_percent,
            "alert": res.alert_level
        })

        if res.alert_level != prior_alert:
            alert_transitions.append((i + 1, prior_alert, res.alert_level, res.rul_percent))
            prior_alert = res.alert_level

        # Visual progress bar
        bar_len = 20
        filled = int((res.rul_percent / 100.0) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        # Color codes for terminal output
        if res.rul_percent > 30.0:
            status_str = f"\033[92m{res.alert_level:<8}\033[0m [{bar}]"
        elif res.rul_percent > 15.0:
            status_str = f"\033[93m{res.alert_level:<8}\033[0m [{bar}]"
        else:
            status_str = f"\033[91m{res.alert_level:<8}\033[0m [{bar}]"

        if verbose:
            print(f"{i+1:>4} s | {s.rpm:<9.0f} | {s.coolant_temp_c:<10.1f} | {res.stress_factor:<11.2f}x | {res.cumulative_damage:<12.5f} | {res.rul_percent:>6.2f}% | {status_str}")

        if res.rul_percent <= 0.0:
            if verbose:
                print("\n  💀 OIL EXHAUSTION LIMIT REACHED (0.00% RUL)!")
                print(f"  Oil life completely depleted in {i+1} seconds!")
            break

    # Close trip in DB
    repo.end_trip(
        trip_id=trip_id,
        final_rul=engine.rul_percent,
        distance_km=engine.cumulative_distance_km,
        duration_seconds=engine.cumulative_engine_seconds
    )
    repo.save_oil_state(engine)

    # Export to CSV
    if export_csv:
        sim.export_samples_to_csv(samples[:len(history)], export_csv)
        sim.export_samples_to_csv(samples[:len(history)], "matlab_telemetry_extreme_stress.csv")

    if verbose:
        print("\n" + "=" * 78)
        print("  SUMMARY OF CATASTROPHIC DRAIN RESULTS:")
        print(f"  • Initial RUL:             100.00%")
        print(f"  • Final RUL:               {engine.rul_percent:.2f}%")
        print(f"  • Total Time to Deplete:   {len(history)} seconds")
        print(f"  • Peak Stress Multiplier:  {history[0]['stress']:.2f}x standard wear")
        print(f"  • Database Record:         Trip #{trip_id} saved in '{db_path}'")
        print(f"  • Exported Telemetry:      '{export_csv}'")
        print("=" * 78 + "\n")

    return {
        "final_rul": engine.rul_percent,
        "total_steps": len(history),
        "trip_id": trip_id,
        "alert_transitions": alert_transitions,
        "peak_stress": history[0]["stress"]
    }


# ==============================================================================
# Pytest Test Cases
# ==============================================================================

class TestRapidOilDrain:
    """Automated assertions verifying rapid oil life depletion under extreme stress."""

    def test_rapid_oil_drain_to_zero(self):
        """Verifies that catastrophic operating parameters completely deplete oil RUL to 0%."""
        res = run_rapid_oil_drain_simulation(
            target_drain_seconds=50,
            rpm_torture=24000.0,
            temp_torture=138.0,
            load_torture=100.0,
            db_path="oil_monitor.db",
            export_csv="rapid_oil_drain_log.csv",
            verbose=False
        )

        assert res["final_rul"] == 0.0
        assert res["total_steps"] <= 45
        assert res["peak_stress"] > 400.0  # Massive shear and thermal multipliers

    def test_alert_threshold_escalation(self):
        """Verifies that alert levels escalate properly: NORMAL -> WARNING -> CRITICAL as RUL plunges."""
        res = run_rapid_oil_drain_simulation(
            target_drain_seconds=40,
            rpm_torture=24000.0,
            temp_torture=138.0,
            load_torture=100.0,
            db_path="oil_monitor.db",
            export_csv=None,
            verbose=False
        )

        transitions = [t[2] for t in res["alert_transitions"]]
        assert "WARNING" in transitions
        assert "CRITICAL" in transitions


if __name__ == "__main__":
    # When executed directly, run the animated demonstration
    run_rapid_oil_drain_simulation()
