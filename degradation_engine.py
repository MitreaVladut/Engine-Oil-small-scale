"""
degradation_engine.py
---------------------
Algorithmic Engine Oil Life Monitoring (OLM) Mathematical Processing Engine.
Calculates continuous oil Remaining Useful Life (RUL, %) and additive concentration
recovery for the 2004 Skoda Fabia 1.4L platform.

Meets Functional Requirements: FR4 (RUL calculation), FR5 (top-up blending)
Meets Non-Functional Requirements: NFR2 (configurable coefficients), NFR4 (modular, unit-testable)
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any
from datetime import datetime


@dataclass
class OilConfig:
    """Configurable coefficients and reference parameters for the oil degradation model."""
    oil_type: str = "Semi-Synthetic"
    base_mileage_km: float = 10000.0          # L_base: 5,000 (Mineral), 10,000 (Semi-Synth), 15,000 (Synth)
    revs_per_km: float = 2500.0               # rho_ref: nominal engine revolutions per km
    sump_capacity_liters: float = 3.7         # V_s: Skoda Fabia 1.4L oil sump capacity
    default_mixing_efficiency: float = 0.95   # eta: additive dispersion efficiency (0.0 to 1.0]

    # RPM mechanical shear parameters
    rpm_threshold: float = 3500.0             # Above this RPM, quadratic shear penalty activates
    rpm_scale: float = 1000.0                 # Denominator in shear scaling formula
    rpm_exponent: float = 2.0                 # Exponent for high RPM penalty

    # Coolant thermal degradation & condensation parameters
    temp_cold_threshold: float = 70.0         # Below 70 C: cold-start condensation / fuel dilution
    temp_hot_threshold: float = 100.0         # Above 100 C: thermal stress / oxidation
    temp_penalty_cold: float = 2.0            # Penalty multiplier for cold operation
    temp_penalty_normal: float = 1.0          # Multiplier for optimal window [70, 100] C
    temp_penalty_hot: float = 1.5             # Penalty multiplier for overheating (> 100 C)

    # Engine load parameters
    load_base_multiplier: float = 0.8         # M_load at 0% load
    load_slope_multiplier: float = 0.4        # M_load scales to 1.2 at 100% load

    # Alert thresholds (RUL %)
    alert_warning_threshold: float = 30.0     # Amber alert at <= 30%
    alert_critical_threshold: float = 15.0    # Red alert at <= 15%

    @property
    def reference_budget_revs(self) -> float:
        """Reference engine revolution budget: N_ref = L_base * rho_ref."""
        return self.base_mileage_km * self.revs_per_km

    @classmethod
    def from_oil_type(cls, oil_type: str, sump_capacity_liters: float = 3.7) -> "OilConfig":
        """Factory helper creating standard literature-calibrated profiles."""
        oil_clean = oil_type.strip().lower()
        if "mineral" in oil_clean:
            return cls(oil_type="Mineral", base_mileage_km=5000.0, sump_capacity_liters=sump_capacity_liters)
        elif "fully" in oil_clean or "full synthetic" in oil_clean or "synthetic" == oil_clean:
            return cls(oil_type="Fully Synthetic", base_mileage_km=15000.0, sump_capacity_liters=sump_capacity_liters)
        else:
            return cls(oil_type="Semi-Synthetic", base_mileage_km=10000.0, sump_capacity_liters=sump_capacity_liters)


@dataclass
class TelemetrySample:
    """Normalized OBD-II telemetry sample."""
    timestamp: datetime
    rpm: float
    speed_kmh: float
    coolant_temp_c: float
    engine_load_pct: float
    delta_t: float = 1.0                      # Time elapsed since prior sample in seconds


@dataclass
class DegradationResult:
    """Result of processing a single telemetry sample through the degradation model."""
    delta_n: float                            # Revolutions in this sample interval
    f_rpm: float                              # Mechanical shear factor M_RPM
    f_temp: float                             # Thermal factor M_Temp
    f_load: float                             # Load factor M_Load
    stress_factor: float                      # Composite stress factor S = M_RPM * M_Temp * M_Load
    delta_damage: float                       # Incremental damage Delta_D
    cumulative_damage: float                  # Running damage D in [0.0, 1.0]
    rul_percent: float                        # Remaining useful life in [0.0, 100.0] %
    distance_increment_km: float              # Incremental distance traveled in km
    alert_level: str                          # 'NORMAL', 'WARNING', or 'CRITICAL'


class DegradationEngine:
    """
    Continuous numerical integrator for engine oil Remaining Useful Life (RUL, %).
    Implements multi-variable mechanical/thermal stress weighting and additive replenishment.
    """

    def __init__(self, config: Optional[OilConfig] = None, initial_damage: float = 0.0):
        self.config = config or OilConfig()
        self.damage = max(0.0, min(1.0, float(initial_damage)))
        self.cumulative_revolutions: float = 0.0
        self.cumulative_distance_km: float = 0.0
        self.cumulative_engine_seconds: float = 0.0
        self.processed_samples_count: int = 0

    @property
    def rul_percent(self) -> float:
        """Remaining Useful Life percentage: RUL (%) = max(0, 100 * (1 - D))."""
        return max(0.0, min(100.0, (1.0 - self.damage) * 100.0))

    @property
    def alert_level(self) -> str:
        """Evaluates vehicle alert state based on current RUL %."""
        rul = self.rul_percent
        if rul <= self.config.alert_critical_threshold:
            return "CRITICAL"
        elif rul <= self.config.alert_warning_threshold:
            return "WARNING"
        return "NORMAL"

    def compute_stress_factors(
        self,
        rpm: float,
        coolant_temp_c: float,
        engine_load_pct: float
    ) -> Tuple[float, float, float, float]:
        """
        Computes the three dimensionless degradation multipliers and the composite stress factor S.
        
        Returns:
            (f_rpm, f_temp, f_load, composite_stress)
        """
        # 1. Mechanical shear multiplier M_RPM
        rpm_val = max(0.0, float(rpm))
        if rpm_val <= self.config.rpm_threshold:
            f_rpm = 1.0
        else:
            f_rpm = 1.0 + ((rpm_val - self.config.rpm_threshold) / self.config.rpm_scale) ** self.config.rpm_exponent

        # 2. Thermal & fuel-dilution penalty multiplier M_Temp
        temp_val = float(coolant_temp_c)
        if temp_val < self.config.temp_cold_threshold:
            f_temp = self.config.temp_penalty_cold
        elif temp_val <= self.config.temp_hot_threshold:
            f_temp = self.config.temp_penalty_normal
        else:
            f_temp = self.config.temp_penalty_hot

        # 3. Calculated engine load multiplier M_Load
        load_clamped = max(0.0, min(100.0, float(engine_load_pct)))
        f_load = self.config.load_base_multiplier + self.config.load_slope_multiplier * (load_clamped / 100.0)

        # Composite stress factor S
        composite_stress = f_rpm * f_temp * f_load
        return f_rpm, f_temp, f_load, composite_stress

    def process_sample(self, sample: TelemetrySample) -> DegradationResult:
        """
        Processes one telemetry sample, updates internal counters and damage state.
        
        Mathematical formulas:
            Delta_N = omega * Delta_t / 60
            S = f_rpm * f_temp * f_load
            Delta_D = (Delta_N / N_ref) * S
            D_new = min(1.0, D_prior + Delta_D)
        """
        # Safeguard abnormal time steps (e.g. between disconnected trips)
        dt = max(0.001, min(60.0, float(sample.delta_t)))
        omega = max(0.0, float(sample.rpm))
        speed = max(0.0, float(sample.speed_kmh))

        # Crankshaft revolutions in this step
        delta_n = (omega * dt) / 60.0

        # Stress factors
        f_rpm, f_temp, f_load, stress = self.compute_stress_factors(
            rpm=omega,
            coolant_temp_c=sample.coolant_temp_c,
            engine_load_pct=sample.engine_load_pct
        )

        # Damage increment
        n_ref = self.config.reference_budget_revs
        delta_damage = (delta_n / n_ref) * stress

        # State update
        self.cumulative_revolutions += delta_n
        self.cumulative_engine_seconds += dt
        delta_km = (speed * dt) / 3600.0
        self.cumulative_distance_km += delta_km
        self.damage = min(1.0, self.damage + delta_damage)
        self.processed_samples_count += 1

        return DegradationResult(
            delta_n=delta_n,
            f_rpm=f_rpm,
            f_temp=f_temp,
            f_load=f_load,
            stress_factor=stress,
            delta_damage=delta_damage,
            cumulative_damage=self.damage,
            rul_percent=self.rul_percent,
            distance_increment_km=delta_km,
            alert_level=self.alert_level
        )

    def apply_top_up(
        self,
        volume_liters: float,
        oil_type: Optional[str] = None,
        mixing_efficiency: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Updates the degradation state following manual oil replenishment.
        
        Formula:
            D_new = D_prior * (1 - eta * V_add / V_s)
            H_new = ((V_s - eta * V_add) * H_prior + eta * V_add * 100) / V_s
        """
        v_add = max(0.0, float(volume_liters))
        v_s = self.config.sump_capacity_liters
        eta = mixing_efficiency if mixing_efficiency is not None else self.config.default_mixing_efficiency
        eta = max(0.1, min(1.0, float(eta)))

        # Cap added volume to sump capacity
        effective_v_add = min(v_s, v_add)

        old_damage = self.damage
        old_rul = self.rul_percent

        # Top-up damage attenuation
        recovery_fraction = eta * (effective_v_add / v_s)
        new_damage = old_damage * (1.0 - recovery_fraction)
        self.damage = max(0.0, min(1.0, new_damage))
        new_rul = self.rul_percent

        # Optionally update oil type if specified
        if oil_type:
            new_cfg = OilConfig.from_oil_type(oil_type, sump_capacity_liters=v_s)
            self.config = new_cfg

        return {
            "volume_liters": v_add,
            "effective_volume_liters": effective_v_add,
            "sump_capacity_liters": v_s,
            "mixing_efficiency": eta,
            "prior_damage": old_damage,
            "new_damage": self.damage,
            "prior_rul": old_rul,
            "new_rul": new_rul,
            "rul_gain": new_rul - old_rul
        }

    def apply_full_oil_change(
        self,
        new_oil_type: Optional[str] = None,
        sump_capacity_liters: Optional[float] = None
    ) -> Dict[str, Any]:
        """Resets engine oil degradation following complete oil drainage and fresh oil fill."""
        prior_rul = self.rul_percent
        prior_damage = self.damage

        self.damage = 0.0
        self.cumulative_revolutions = 0.0
        self.cumulative_distance_km = 0.0
        self.cumulative_engine_seconds = 0.0

        if new_oil_type or sump_capacity_liters:
            sump = sump_capacity_liters or self.config.sump_capacity_liters
            otype = new_oil_type or self.config.oil_type
            self.config = OilConfig.from_oil_type(otype, sump_capacity_liters=sump)

        return {
            "prior_damage": prior_damage,
            "new_damage": 0.0,
            "prior_rul": prior_rul,
            "new_rul": 100.0,
            "oil_type": self.config.oil_type
        }

    def predict_remaining_km(self) -> float:
        """
        Forecasts remaining driving distance before oil reaches 0% RUL.
        Based on accumulated real distance and accrued damage, or nominal baseline.
        """
        if self.rul_percent <= 0.0:
            return 0.0

        if self.cumulative_distance_km > 0.5 and self.damage > 0.0001:
            # Empirical degradation rate per km
            damage_per_km = self.damage / self.cumulative_distance_km
            remaining_damage_capacity = 1.0 - self.damage
            return remaining_damage_capacity / damage_per_km
        else:
            # Nominal budget based on baseline mileage
            return (self.rul_percent / 100.0) * self.config.base_mileage_km

    def get_state(self) -> Dict[str, Any]:
        """Serializes internal state for database persistence or checkpoints."""
        return {
            "oil_type": self.config.oil_type,
            "base_mileage_km": self.config.base_mileage_km,
            "sump_capacity_liters": self.config.sump_capacity_liters,
            "damage": self.damage,
            "rul_percent": self.rul_percent,
            "cumulative_revolutions": self.cumulative_revolutions,
            "cumulative_distance_km": self.cumulative_distance_km,
            "cumulative_engine_seconds": self.cumulative_engine_seconds,
            "processed_samples_count": self.processed_samples_count,
            "alert_level": self.alert_level
        }

    def load_state(self, state: Dict[str, Any]) -> None:
        """Restores engine state from a serialized dictionary or database record."""
        self.damage = float(state.get("damage", 0.0))
        self.cumulative_revolutions = float(state.get("cumulative_revolutions", 0.0))
        self.cumulative_distance_km = float(state.get("cumulative_distance_km", 0.0))
        self.cumulative_engine_seconds = float(state.get("cumulative_engine_seconds", 0.0))
        self.processed_samples_count = int(state.get("processed_samples_count", 0))

        if "oil_type" in state:
            sump = float(state.get("sump_capacity_liters", self.config.sump_capacity_liters))
            base_km = float(state.get("base_mileage_km", self.config.base_mileage_km))
            self.config.oil_type = state["oil_type"]
            self.config.sump_capacity_liters = sump
            self.config.base_mileage_km = base_km
