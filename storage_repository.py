"""
storage_repository.py
---------------------
SQLite-based Persistence Layer for the Oil Life Monitoring (OLM) System.
Implements the Repository Pattern for trip logs, telemetry streams,
oil degradation state, and physical maintenance events.

Meets Functional Requirements: FR5 (log top-ups / changes), FR6 (store trips & samples)
Meets Architecture Requirements: Section 4.1 Storage Layer (Repository Pattern)
"""

import sqlite3
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from degradation_engine import OilConfig, TelemetrySample, DegradationResult, DegradationEngine


class StorageRepository:
    """Thread-safe SQLite repository for the automotive predictive maintenance platform."""

    DEFAULT_DB_PATH = "oil_monitor.db"

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self.initialize_schema()

    @contextmanager
    def _connection(self):
        """Context manager guaranteeing connection commit and immediate close on exit."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        """Creates database tables and indices if they do not exist."""
        with self._connection() as conn:
            cursor = conn.cursor()

            # 1. Active Vehicle Oil State Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS oil_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                vehicle_model TEXT NOT NULL DEFAULT 'Skoda Fabia 1.4L',
                sump_capacity_liters REAL NOT NULL DEFAULT 3.7,
                oil_type TEXT NOT NULL DEFAULT 'Semi-Synthetic',
                base_mileage_km REAL NOT NULL DEFAULT 10000.0,
                revs_per_km REAL NOT NULL DEFAULT 2500.0,
                cumulative_revolutions REAL NOT NULL DEFAULT 0.0,
                cumulative_damage REAL NOT NULL DEFAULT 0.0,
                current_rul_percent REAL NOT NULL DEFAULT 100.0,
                total_engine_hours REAL NOT NULL DEFAULT 0.0,
                total_distance_km REAL NOT NULL DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. Trip Logging Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trips (
                trip_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                scenario_name TEXT,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                duration_seconds REAL DEFAULT 0.0,
                distance_km REAL DEFAULT 0.0,
                initial_rul REAL NOT NULL,
                final_rul REAL,
                rul_drop_percent REAL DEFAULT 0.0
            );
            """)

            # 3. High-Frequency Telemetry Samples
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS telemetry_samples (
                sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                rpm REAL NOT NULL,
                speed_kmh REAL NOT NULL,
                coolant_temp_c REAL NOT NULL,
                engine_load_pct REAL NOT NULL,
                delta_t REAL NOT NULL,
                stress_factor REAL NOT NULL,
                incremental_damage REAL NOT NULL,
                current_rul REAL NOT NULL,
                FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE
            );
            """)

            # 4. Oil Maintenance & Top-Up Events
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                volume_liters REAL NOT NULL,
                oil_grade TEXT NOT NULL,
                mixing_efficiency REAL NOT NULL DEFAULT 0.95,
                rul_before REAL NOT NULL,
                rul_after REAL NOT NULL,
                notes TEXT
            );
            """)

            # Indices for analytical querying
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_trip ON telemetry_samples(trip_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts ON telemetry_samples(timestamp);")

    def get_or_create_oil_state(self, default_config: Optional[OilConfig] = None) -> Dict[str, Any]:
        """Loads the persisted oil health state or creates a default state."""
        cfg = default_config or OilConfig()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM oil_state WHERE id = 1;")
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Insert initial 100% health state
            cursor.execute("""
            INSERT INTO oil_state (
                id, vehicle_model, sump_capacity_liters, oil_type,
                base_mileage_km, revs_per_km, cumulative_revolutions,
                cumulative_damage, current_rul_percent, total_engine_hours,
                total_distance_km
            ) VALUES (1, 'Skoda Fabia 1.4L', ?, ?, ?, ?, 0.0, 0.0, 100.0, 0.0, 0.0);
            """, (cfg.sump_capacity_liters, cfg.oil_type, cfg.base_mileage_km, cfg.revs_per_km))

            cursor.execute("SELECT * FROM oil_state WHERE id = 1;")
            return dict(cursor.fetchone())

    def save_oil_state(self, engine: DegradationEngine) -> None:
        """Persists the in-memory DegradationEngine state into the database."""
        state = engine.get_state()
        hours = state["cumulative_engine_seconds"] / 3600.0
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE oil_state SET
                oil_type = ?,
                base_mileage_km = ?,
                sump_capacity_liters = ?,
                cumulative_revolutions = ?,
                cumulative_damage = ?,
                current_rul_percent = ?,
                total_engine_hours = ?,
                total_distance_km = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE id = 1;
            """, (
                state["oil_type"],
                state["base_mileage_km"],
                state["sump_capacity_liters"],
                state["cumulative_revolutions"],
                state["damage"],
                state["rul_percent"],
                hours,
                state["cumulative_distance_km"]
            ))

    def start_trip(self, source_type: str, scenario_name: str, initial_rul: float) -> int:
        """Creates a new trip log entry and returns its trip_id."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO trips (
                source_type, scenario_name, start_time, initial_rul
            ) VALUES (?, ?, CURRENT_TIMESTAMP, ?);
            """, (source_type, scenario_name, initial_rul))
            return cursor.lastrowid

    def log_sample(self, trip_id: int, sample: TelemetrySample, result: DegradationResult) -> None:
        """Appends a single telemetry record and its calculated damage values."""
        ts_str = sample.timestamp.strftime("%Y-%m-%d %H:%M:%S") if isinstance(sample.timestamp, datetime) else str(sample.timestamp)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO telemetry_samples (
                trip_id, timestamp, rpm, speed_kmh, coolant_temp_c,
                engine_load_pct, delta_t, stress_factor, incremental_damage,
                current_rul
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                trip_id, ts_str, sample.rpm, sample.speed_kmh,
                sample.coolant_temp_c, sample.engine_load_pct, sample.delta_t,
                result.stress_factor, result.delta_damage, result.rul_percent
            ))

    def log_samples_batch(self, trip_id: int, records: List[Tuple[TelemetrySample, DegradationResult]]) -> None:
        """Batch inserts multiple samples for optimal database throughput."""
        rows = []
        for sample, result in records:
            ts_str = sample.timestamp.strftime("%Y-%m-%d %H:%M:%S") if isinstance(sample.timestamp, datetime) else str(sample.timestamp)
            rows.append((
                trip_id, ts_str, sample.rpm, sample.speed_kmh,
                sample.coolant_temp_c, sample.engine_load_pct, sample.delta_t,
                result.stress_factor, result.delta_damage, result.rul_percent
            ))

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
            INSERT INTO telemetry_samples (
                trip_id, timestamp, rpm, speed_kmh, coolant_temp_c,
                engine_load_pct, delta_t, stress_factor, incremental_damage,
                current_rul
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, rows)

    def end_trip(self, trip_id: int, final_rul: float, distance_km: float, duration_seconds: float) -> None:
        """Closes an active trip with final telemetry metrics."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT initial_rul FROM trips WHERE trip_id = ?;", (trip_id,))
            row = cursor.fetchone()
            init_rul = row["initial_rul"] if row else final_rul
            drop = max(0.0, init_rul - final_rul)

            cursor.execute("""
            UPDATE trips SET
                end_time = CURRENT_TIMESTAMP,
                duration_seconds = ?,
                distance_km = ?,
                final_rul = ?,
                rul_drop_percent = ?
            WHERE trip_id = ?;
            """, (duration_seconds, distance_km, final_rul, drop, trip_id))

    def log_maintenance_event(
        self,
        event_type: str,
        volume_liters: float,
        oil_grade: str,
        mixing_efficiency: float,
        rul_before: float,
        rul_after: float,
        notes: str = ""
    ) -> int:
        """Records an oil top-up or complete drain-and-fill event."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO maintenance_events (
                event_type, volume_liters, oil_grade, mixing_efficiency,
                rul_before, rul_after, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (event_type, volume_liters, oil_grade, mixing_efficiency, rul_before, rul_after, notes))
            return cursor.lastrowid

    def get_trips(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves past recorded trips."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trips ORDER BY trip_id DESC LIMIT ?;", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_trip_samples(self, trip_id: int) -> List[Dict[str, Any]]:
        """Retrieves all telemetry points for a given trip."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telemetry_samples WHERE trip_id = ? ORDER BY sample_id ASC;", (trip_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_maintenance_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves past maintenance logs."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM maintenance_events ORDER BY event_id DESC LIMIT ?;", (limit,))
            return [dict(r) for r in cursor.fetchall()]
