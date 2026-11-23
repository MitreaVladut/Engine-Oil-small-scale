"""
data_sources.py
---------------
Unified Data Ingestion & Strategy Layer for OBD-II Telemetry.
Enables transparent switching between physical ELM327 hardware,
CSV historical logs, and simulated drive cycles.

Meets Functional Requirements: FR1 (poll RPM/Speed/Temp/Load), FR2 (derive delta_t), FR3 (unified interface)
Meets Architectural Patterns: Strategy Pattern (Section 4.1), Adapter Pattern
"""

from abc import ABC, abstractmethod
from typing import Optional, Generator, Dict, Any, Callable
from datetime import datetime
import csv
import time
import threading

from degradation_engine import TelemetrySample

try:
    import obd
    OBD_AVAILABLE = True
except ImportError:
    OBD_AVAILABLE = False


class IDataSource(ABC):
    """Abstract Strategy interface for all vehicle telemetry sources."""

    @abstractmethod
    def start(self) -> bool:
        """Initializes connection or opens file stream."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Closes hardware interface or file descriptor."""
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """Returns True if the data source is currently streaming."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Returns human-readable name of the source strategy."""
        pass

    @abstractmethod
    def read_next_sample(self) -> Optional[TelemetrySample]:
        """Fetches the next normalized telemetry frame, or None if end-of-stream."""
        pass


class CSVReplayDataSource(IDataSource):
    """
    Replays recorded vehicle telemetry from CSV files (e.g. car_telemetry_log.csv).
    Handles timestamp parsing, abnormal delta_t capping, and variable replay pacing.
    """

    def __init__(self, csv_filepath: str, replay_speed: float = 1.0, loop: bool = False):
        self.csv_filepath = csv_filepath
        self.replay_speed = max(0.1, float(replay_speed))
        self.loop = loop
        self._file = None
        self._reader = None
        self._active = False
        self._last_timestamp: Optional[datetime] = None
        self._rows_read = 0

    def start(self) -> bool:
        try:
            self._file = open(self.csv_filepath, mode='r', newline='', encoding='utf-8')
            self._reader = csv.DictReader(self._file)
            self._active = True
            self._last_timestamp = None
            self._rows_read = 0
            return True
        except Exception as e:
            print(f"[!] Error opening CSV replay file {self.csv_filepath}: {e}")
            self._active = False
            return False

    def stop(self) -> None:
        self._active = False
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        self._reader = None

    def is_active(self) -> bool:
        return self._active

    def get_source_name(self) -> str:
        return f"CSV Replay ({self.csv_filepath})"

    def read_next_sample(self) -> Optional[TelemetrySample]:
        if not self._active or not self._reader:
            return None

        try:
            row = next(self._reader)
            self._rows_read += 1
        except StopIteration:
            if self.loop:
                self._file.seek(0)
                self._reader = csv.DictReader(self._file)
                self._last_timestamp = None
                return self.read_next_sample()
            else:
                self.stop()
                return None
        except Exception as e:
            print(f"[!] Replay read error: {e}")
            self.stop()
            return None

        # Parse row fields (matching car_logger.py schema)
        ts_raw = row.get("Timestamp", "")
        try:
            current_dt = datetime.strptime(ts_raw.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            current_dt = datetime.now()

        # Derive delta_t
        if self._last_timestamp is not None:
            raw_dt = (current_dt - self._last_timestamp).total_seconds()
            # Guard against time anomalies between separate logging sessions
            delta_t = max(0.1, min(5.0, raw_dt))
        else:
            delta_t = 1.0

        self._last_timestamp = current_dt

        try:
            rpm = float(row.get("RPM", 0.0))
            speed = float(row.get("Speed_KMH", 0.0))
            temp = float(row.get("Coolant_Temp_C", 60.0))
            load = float(row.get("Engine_Load_Pct", 10.0))
        except (ValueError, TypeError):
            rpm, speed, temp, load = 0.0, 0.0, 60.0, 10.0

        return TelemetrySample(
            timestamp=current_dt,
            rpm=rpm,
            speed_kmh=speed,
            coolant_temp_c=temp,
            engine_load_pct=load,
            delta_t=delta_t
        )


class RealOBDDataSource(IDataSource):
    """
    Live acquisition strategy polling real vehicle ECU via an ELM327 Bluetooth/USB adapter.
    Implements prioritized query loops, drop-frame caching, and ISO 9141-2 / ISO 14230-4 fallback.
    """

    def __init__(self, port_name: str = "COM5", baudrate: int = 38400, timeout: int = 15):
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None
        self._active = False
        self._last_read_time: Optional[float] = None
        self.last_valid_values = {
            "RPM": 0.0,
            "Speed": 0.0,
            "Coolant_Temp": 70.0,
            "Engine_Load": 0.0
        }

    def start(self) -> bool:
        if not OBD_AVAILABLE:
            print("[!] python-obd library not installed or hardware serial unavailable.")
            return False

        print(f"[*] Connecting to ELM327 on {self.port_name}...")
        try:
            # Primary: Protocol 3 (ISO 9141-2 for Skoda Fabia 2004)
            self.connection = obd.OBD(
                portstr=self.port_name,
                baudrate=self.baudrate,
                protocol="3",
                fast=False,
                timeout=self.timeout
            )
            if not self.connection.is_connected():
                print("[!] Protocol 3 failed. Attempting Protocol 5 (ISO 14230-4 KWP)...")
                self.connection = obd.OBD(
                    portstr=self.port_name,
                    baudrate=self.baudrate,
                    protocol="5",
                    fast=False,
                    timeout=self.timeout
                )

            if self.connection.is_connected():
                self._active = True
                self._last_read_time = time.time()
                print(f"[+] OBD Connected successfully via {self.connection.protocol_name()}")
                return True
            else:
                print("[-] OBD Connection failed.")
                self._active = False
                return False
        except Exception as e:
            print(f"[!] OBD Connection Exception: {e}")
            self._active = False
            return False

    def stop(self) -> None:
        self._active = False
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def is_active(self) -> bool:
        return self._active and self.connection is not None and self.connection.is_connected()

    def get_source_name(self) -> str:
        return f"Real OBD-II ({self.port_name})"

    def _query_safely(self, command, key: str) -> float:
        if not self.connection:
            return self.last_valid_values[key]
        try:
            resp = self.connection.query(command)
            if not resp.is_null() and resp.value is not None:
                val = float(resp.value.magnitude)
                self.last_valid_values[key] = val
                return val
        except Exception:
            pass
        return self.last_valid_values[key]

    def read_next_sample(self) -> Optional[TelemetrySample]:
        if not self.is_active():
            return None

        now = time.time()
        delta_t = (now - self._last_read_time) if self._last_read_time else 1.0
        delta_t = max(0.1, min(5.0, delta_t))
        self._last_read_time = now

        # Query PIDs with slight delay to prevent ISO 9141 bus collision
        rpm = self._query_safely(obd.commands.RPM, "RPM")
        time.sleep(0.04)
        speed = self._query_safely(obd.commands.SPEED, "Speed")
        time.sleep(0.04)
        temp = self._query_safely(obd.commands.COOLANT_TEMP, "Coolant_Temp")
        time.sleep(0.04)
        load = self._query_safely(obd.commands.ENGINE_LOAD, "Engine_Load")

        return TelemetrySample(
            timestamp=datetime.now(),
            rpm=rpm,
            speed_kmh=speed,
            coolant_temp_c=temp,
            engine_load_pct=load,
            delta_t=delta_t
        )


class GeneratorDataSource(IDataSource):
    """
    Adapter bridging in-memory scripted drive cycles and simulation engines into the standard IDataSource stream.
    """

    def __init__(self, sample_generator_fn: Callable[[], Generator[TelemetrySample, None, None]], name: str = "Drive Cycle"):
        self._gen_fn = sample_generator_fn
        self._name = name
        self._generator: Optional[Generator[TelemetrySample, None, None]] = None
        self._active = False

    def start(self) -> bool:
        self._generator = self._gen_fn()
        self._active = True
        return True

    def stop(self) -> None:
        self._active = False
        self._generator = None

    def is_active(self) -> bool:
        return self._active

    def get_source_name(self) -> str:
        return f"Simulation: {self._name}"

    def read_next_sample(self) -> Optional[TelemetrySample]:
        if not self._active or self._generator is None:
            return None
        try:
            return next(self._generator)
        except StopIteration:
            self.stop()
            return None
