"""
drive_cycle_simulator.py
------------------------
Deterministic Vehicle Dynamics, Engine Speed, and Coolant Thermal Simulator.
Generates reproducible synthetic drive cycles for predictive oil degradation evaluation
and exports telemetry matching the car_telemetry_log.csv format.

Meets Requirements:
- FR3 (unified interface acceptance)
- NFR3 (reproducible fixed scenarios)
- Section 6 Prototype Demonstration (Cold Short-Trip vs. Steady Highway vs. Aggressive)
"""

import math
import csv
from datetime import datetime, timedelta
from typing import List, Generator, Optional
from degradation_engine import TelemetrySample


class DriveCycleSimulator:
    """
    Simplified physics-based vehicular simulator representing a 2004 Skoda Fabia 1.4L.
    Models engine speed, gear ratios, road drag, and lumped coolant thermal warm-up dynamics.
    """

    def __init__(self, ambient_temp_c: float = 20.0):
        self.ambient_temp_c = ambient_temp_c

    def _simulate_thermal_step(
        self,
        current_temp: float,
        rpm: float,
        load_pct: float,
        speed_kmh: float,
        dt: float
    ) -> float:
        """
        Lumped-capacitance thermal step with thermostat regulation.
        Combustion heat generation warms coolant towards 90 C; airflow cools it.
        """
        target_operating_temp = 90.0
        # Heat generation proportional to engine power output
        heat_gen = (rpm / 3000.0) * (load_pct / 100.0) * 1.8
        # Radiator cooling and ram-air effect
        cooling_factor = 0.015 + (speed_kmh / 120.0) * 0.02

        if current_temp < 85.0:
            # Thermostat closed: rapid warm-up
            dT = (heat_gen * 2.2 - (current_temp - self.ambient_temp_c) * 0.008) * dt
        else:
            # Thermostat active: regulates near 90 C
            delta_target = current_temp - target_operating_temp
            dT = (heat_gen * 1.0 - delta_target * cooling_factor) * dt

        # Prevent unrealistic leaps
        new_temp = current_temp + dT
        return max(self.ambient_temp_c, min(115.0, new_temp))

    def generate_cold_short_trip(
        self,
        duration_seconds: int = 600,
        start_time: Optional[datetime] = None
    ) -> List[TelemetrySample]:
        """
        Scenario 1: Cold Engine Short-Trip (Urban commute).
        Characteristics:
          - Initial coolant temperature = Ambient (e.g. 15-20 C)
          - Frequent stops, idling (0 km/h, 780 RPM)
          - City speeds 0-45 km/h, moderate acceleration
          - Engine fails to reach full operating temperature (< 68 C)
          - Triggers the 2.0x Cold Start / Condensation Penalty Factor
        """
        start_dt = start_time or datetime.now()
        samples: List[TelemetrySample] = []
        coolant_temp = self.ambient_temp_c
        speed = 0.0

        for t in range(duration_seconds):
            # Synthetic urban stop-and-go cycle (period of 90s)
            phase = (t % 90)
            if phase < 20:
                # Idling at traffic light
                speed = 0.0
                rpm = 780.0 + 15.0 * math.sin(t * 0.5)
                load = 4.0 + 2.0 * math.sin(t * 0.2)
            elif phase < 45:
                # Acceleration to 35-45 km/h
                accel_t = (phase - 20) / 25.0
                speed = 42.0 * math.sin(accel_t * (math.pi / 2))
                rpm = 1800.0 + 1200.0 * accel_t
                load = 45.0 + 25.0 * accel_t
            elif phase < 75:
                # Moderate city cruising
                speed = 38.0 + 4.0 * math.sin(t * 0.3)
                rpm = 2100.0 + 100.0 * math.sin(t * 0.3)
                load = 22.0 + 5.0 * math.sin(t * 0.2)
            else:
                # Deceleration / braking
                decel_t = (90 - phase) / 15.0
                speed = 38.0 * decel_t
                rpm = 1200.0 * decel_t + 780.0
                load = 3.0

            coolant_temp = self._simulate_thermal_step(coolant_temp, rpm, load, speed, dt=1.0)
            sample_time = start_dt + timedelta(seconds=t)

            samples.append(TelemetrySample(
                timestamp=sample_time,
                rpm=round(rpm, 1),
                speed_kmh=round(speed, 1),
                coolant_temp_c=round(coolant_temp, 1),
                engine_load_pct=round(load, 2),
                delta_t=1.0
            ))

        return samples

    def generate_steady_highway(
        self,
        duration_seconds: int = 600,
        start_time: Optional[datetime] = None
    ) -> List[TelemetrySample]:
        """
        Scenario 2: Steady Highway Cruising.
        Characteristics:
          - Engine pre-warmed to optimal window (88-92 C)
          - Steady speeds 90-110 km/h, 5th gear cruising (2600-2900 RPM)
          - Optimal thermal window (1.0x penalty factor)
          - Low engine load (18-28%)
        """
        start_dt = start_time or datetime.now()
        samples: List[TelemetrySample] = []
        coolant_temp = 89.5

        for t in range(duration_seconds):
            # Smooth minor highway variations
            speed = 98.0 + 6.0 * math.sin(t * 0.05) + 2.0 * math.cos(t * 0.12)
            rpm = 2650.0 + 150.0 * math.sin(t * 0.05)
            load = 22.0 + 4.0 * math.sin(t * 0.08)

            coolant_temp = self._simulate_thermal_step(coolant_temp, rpm, load, speed, dt=1.0)
            sample_time = start_dt + timedelta(seconds=t)

            samples.append(TelemetrySample(
                timestamp=sample_time,
                rpm=round(rpm, 1),
                speed_kmh=round(speed, 1),
                coolant_temp_c=round(coolant_temp, 1),
                engine_load_pct=round(load, 2),
                delta_t=1.0
            ))

        return samples

    def generate_aggressive_high_stress(
        self,
        duration_seconds: int = 600,
        start_time: Optional[datetime] = None
    ) -> List[TelemetrySample]:
        """
        Scenario 3: Aggressive High-RPM / Mountain Pass Driving.
        Characteristics:
          - Elevated RPM exceeding 3500 (3800 - 5200 RPM)
          - High thermal stress (coolant reaching 102 - 106 C)
          - High engine torque load (50 - 90%)
          - Compounded mechanical shear and thermal oxidation penalties
        """
        start_dt = start_time or datetime.now()
        samples: List[TelemetrySample] = []
        coolant_temp = 92.0

        for t in range(duration_seconds):
            cycle_phase = (t % 40)
            if cycle_phase < 25:
                # Heavy throttle acceleration
                accel_norm = cycle_phase / 25.0
                rpm = 3400.0 + 2000.0 * accel_norm
                load = 65.0 + 30.0 * accel_norm
                speed = 60.0 + 70.0 * accel_norm
            else:
                # Engine braking / gear change
                rpm = 3800.0 - 1500.0 * ((cycle_phase - 25) / 15.0)
                load = 15.0
                speed = 100.0 - 20.0 * ((cycle_phase - 25) / 15.0)

            coolant_temp = self._simulate_thermal_step(coolant_temp, rpm, load, speed, dt=1.0)
            sample_time = start_dt + timedelta(seconds=t)

            samples.append(TelemetrySample(
                timestamp=sample_time,
                rpm=round(rpm, 1),
                speed_kmh=round(speed, 1),
                coolant_temp_c=round(coolant_temp, 1),
                engine_load_pct=round(load, 2),
                delta_t=1.0
            ))

        return samples

    def generate_catastrophic_torture_cycle(
        self,
        duration_seconds: int = 120,
        rpm_target: float = 24000.0,
        coolant_temp_target: float = 138.0,
        load_target: float = 100.0,
        delta_t_step: float = 2.0,
        start_time: Optional[datetime] = None
    ) -> List[TelemetrySample]:
        """
        Scenario 4: Catastrophic / Unrealistically Severe Torture Test.
        Designed to simulate extreme hypothetical stress far beyond normal road vehicle capability:
          - Extreme RPM (e.g. 20,000 - 25,000 RPM) causing massive mechanical shear penalty (M_RPM > 400x)
          - Severe engine boiling overheating (130 - 145 C, exceeding 100 C threshold)
          - Maximum wide-open throttle load (100%)
          - Rapidly burns through 100% of the oil life budget in under a minute!
        """
        start_dt = start_time or datetime.now()
        samples: List[TelemetrySample] = []
        coolant_temp = coolant_temp_target

        num_steps = int(duration_seconds / delta_t_step)
        for i in range(num_steps):
            # Oscillate slightly around the extreme redline
            rpm = rpm_target + 1200.0 * math.sin(i * 0.4)
            temp = coolant_temp + 3.0 * math.sin(i * 0.2)
            load = min(100.0, load_target - 2.0 * abs(math.cos(i * 0.3)))
            speed = 280.0 + 30.0 * math.sin(i * 0.1)

            sample_time = start_dt + timedelta(seconds=i * delta_t_step)

            samples.append(TelemetrySample(
                timestamp=sample_time,
                rpm=round(rpm, 1),
                speed_kmh=round(speed, 1),
                coolant_temp_c=round(temp, 1),
                engine_load_pct=round(load, 2),
                delta_t=delta_t_step
            ))

        return samples

    @staticmethod
    def export_samples_to_csv(samples: List[TelemetrySample], output_filepath: str) -> None:
        """Exports generated drive cycle samples to CSV matching car_telemetry_log.csv schema."""
        with open(output_filepath, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "RPM", "Speed_KMH", "Coolant_Temp_C", "Engine_Load_Pct"])
            for s in samples:
                ts_str = s.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([ts_str, s.rpm, s.speed_kmh, s.coolant_temp_c, s.engine_load_pct])
        print(f"[+] Exported {len(samples)} telemetry samples to '{output_filepath}'.")
