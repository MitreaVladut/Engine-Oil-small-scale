# Technology Stack & Implementation Roadmap: Algorithmic Engine Oil Life Monitoring System

**Project:** Bachelor Thesis - Practical Case Study & System Prototype  
**Student:** Mitrea Vladut-Cristian  
**Supervisor:** Constantin-Renato Ivănescu  
**Faculty:** Faculty of Automation, Computers and Electronics  
**Target Testbed:** 2004 Skoda Fabia 1.4L (ISO 9141-2 K-Line OBD-II Interface)  

---

## Part 1: Technologies Implemented (Current Working Prototype)

### 1. Automotive Diagnostics & Hardware Interfacing
* **SAE J1979 / OBD-II Standard:** Standardized vehicular diagnostics protocol querying Mode 01 Parameter IDs:
  * `0x0C` – Engine RPM (Calculates crankshaft revolutions & mechanical shear stress)
  * `0x0D` – Vehicle Speed (Accumulates distance; distinguishes idling from highway transit)
  * `0x05` – Coolant Temperature (Evaluates thermal efficiency; flags cold-start condensation & fuel dilution)
  * `0x04` – Calculated Engine Load (Scales degradation rate proportional to engine torque output)
  * `0x1F` – Engine Run Time (Tracks operational duration in seconds independent of distance; city idling stress)
* **ISO 9141-2 (K-Line):** Asynchronous serial protocol operating at 10.4 kbps (with 5-baud initialization) native to the 2004 Skoda Fabia 1.4L ECU.
* **ISO 14230-4 (KWP2000):** Automatic secondary fallback protocol.
* **ELM327 Microcontroller Interpreter:** PIC18F25K80 architecture translating low-level signaling protocols into standard ASCII AT commands.
* **AUTOSKY Bluetooth V4.0 OBD-II Adapter:** Physical wireless interface connecting the car's 16-pin DLC port to the host computer over a virtual COM port (`COM5` at 38,400 baud).

### 2. Core Programming & Diagnostic Libraries
* **Python 3:** Core programming language powering all layers of the software architecture.
* **`python-obd`:** Asynchronous Python wrapper for serial ELM327 connections, command queuing, frame parsing, and reconnection logic.
* **`pyserial`:** Underlying low-level serial communication driver managing virtual RS-232/Bluetooth serial buffers.
* **`Pint`:** Integrated physical unit definition and conversion library.
* **Python Standard Libraries:** `dataclasses`, `sqlite3`, `abc` (abstract base classes for Strategy Pattern), `csv`, `datetime`, `contextlib`, `threading`.

### 3. Mathematics, Data Science & Simulation
* **NumPy:** Vectorized numerical calculations and telemetry array operations.
* **Pandas:** Tabular telemetry manipulation, time-series replay, and data analysis.
* **MATLAB (.m Scripting):** Lumped-capacitance coolant thermal ODE modeling, vehicle longitudinal dynamics, and synthetic drive-cycle generation (`matlab_drive_cycle_sim.m`).
* **Physics-Informed Discrete Integrator:** Continuous mathematical engine computing:
  * Crankshaft rev increments: $\Delta N = \frac{\omega \cdot \Delta t}{60}$
  * Multi-stress factor: $S = M_{RPM}(\omega) \cdot M_{Temp}(T) \cdot M_{Load}(L)$
  * Incremental damage: $\Delta D = \left(\frac{\Delta N}{N_{ref}}\right) \cdot S$
  * Cumulative Remaining Useful Life: $RUL(\%) = 100 \cdot (1 - D)$
  * Additive concentration recovery: $H_{new} = \frac{(V_s - \eta \cdot V_{add}) \cdot H_{prior} + (\eta \cdot V_{add}) \cdot 100}{V_s}$

### 4. Database & Persistence Layer
* **SQLite 3:** Embedded, zero-configuration relational database engine (`oil_monitor.db`).
* **WAL Mode (Write-Ahead Logging):** Configured with foreign key enforcement and ACID transactions to enable concurrent reads and writes between background telemetry threads and the UI.
* **Repository Pattern:** Clean abstraction separating business logic from SQL operations across 4 tables: `oil_state`, `trips`, `telemetry_samples`, and `maintenance_events`.

### 5. Graphical User Interface (GUI) & Real-Time Visualization
* **PyQt6 (Qt 6 Framework):** Hardware-accelerated desktop UI featuring:
  * Custom dark automotive theme palette.
  * Qt Signals & Slots architecture decoupling background data streams from UI rendering.
  * Interactive modal dialogs for oil top-up and full maintenance resets.
  * Replay speed controls (1x up to 50x) and scenario selector.
* **PyQtGraph:** High-performance charting engine rendering multi-trace real-time curves (RUL %, Coolant Temp, Stress Multiplier) with low CPU overhead.

### 6. Testing, Verification & Version Control
* **Pytest:** Automated testing framework executing 13 unit and integration tests (`test_degradation_engine.py`, `test_rapid_oil_drain.py`) validating mathematical bounds, shear/thermal penalties, additive recovery, persistence, and simulation reproducibility.
* **Git:** Distributed version control tracking development milestones.
* **GitHub:** Remote repository hosting at [`MitreaVladut/Engine-Oil-small-scale`](https://github.com/MitreaVladut/Engine-Oil-small-scale).

---

## Part 2: Technologies Remaining to be Implemented (Full Thesis Scope)

### 1. Database & Time-Series Data Management (Scaling up from SQLite)
* **PostgreSQL / TimescaleDB:** Moving from local SQLite to a server-grade time-series relational database for continuous multi-month logging, automated time chunking, hyper-tables, and multi-vehicle fleet synchronization.
* **SQLAlchemy & Alembic:** Full ORM abstraction and automated database schema migration management.

### 2. Embedded Vehicle Hardware & Operating System
* **Raspberry Pi 4 / Pi Zero 2W (Embedded Linux / Raspberry Pi OS):** Deploying the software stack directly inside the car cabin as a headless or touchscreen head unit.
* **`systemd` Service Daemons:** Background service management to automatically start telemetry logging on vehicle ignition (12V accessory sense) and execute clean shutdown.
* **Hardware Watchdog Timers & Power Management HATs (e.g., Pi-Supply / UPS HAT):** Protecting filesystem integrity against abrupt engine power-off.

### 3. Alternative & Embedded UI Frameworks
* **CustomTkinter:** Lightweight, low-overhead UI alternative for smaller resolution embedded touchscreen displays (3.5" or 7" DSI panels) with minimal memory footprint.
* **Web-Based Dashboard Stack (FastAPI / WebSockets + React / Chart.js or Grafana):** Headless vehicle telemetry server broadcasting live engine parameters over Wi-Fi to a passenger smartphone or tablet.

### 4. Advanced Simulation & Modeling Environments
* **MATLAB Simulink (Powertrain Blockset / Simscape Driveline):** Component-level physical simulation (combustion heat flux, radiator thermostat hysteresis, automatic/manual gear ratios) with Hardware-in-the-Loop (HIL) or Software-in-the-Loop (SIL) integration.
* **Virtual Serial Port Emulation (`com0com` on Windows / `pty` / `socat` on Linux):** Paired virtual COM ports for automated mock ELM327 responses and CI/CD stress testing without vehicle connection.

### 5. Advanced Diagnostics Protocols & Hardware Interfaces
* **Direct SocketCAN / CAN Bus Interface (MCP2515 / CANable / PEAK-System):** Upgrading from legacy slow K-Line (10.4 kbps) to high-speed Controller Area Network (CAN bus ISO 15765-4, 500 kbps).
* **Diagnostic Trouble Code (DTC) Poller (SAE J1979 Mode 03 / Mode 04):** Automatic reading, decoding, and clearing of powertrain DTCs related to lubricant failure (e.g., thermostat failure, cylinder misfires).
* **Manufacturer Extended PIDs / KWP1281 / KWP2000 (VAG Specific):** Reading proprietary Volkswagen/Skoda measuring value blocks (oil level sensor where equipped, long-term fuel trim `LTFT`, instantaneous fuel mass flow rate).

### 6. Machine Learning & Predictive Analytics (Condition-Based Maintenance)
* **Scikit-learn / XGBoost / PyTorch:** Developing a hybrid predictive model: combining the physics-based stress integral with supervised machine learning trained on driving pattern clusters to forecast Remaining Useful Life and personalized oil change intervals.
* **Laboratory Oil Analysis Calibration:** Empirical validation against used oil spectrometry samples (Total Base Number - TBN depletion, kinematic viscosity at 100°C, soot %, water content).

### 7. Cloud Telemetry & Remote Alerting
* **MQTT / Eclipse Mosquitto:** Lightweight IoT telemetry protocol for streaming compressed vehicle packets to cloud monitoring endpoints.
* **Push Notifications & Webhooks (Telegram Bot / REST API / Twilio SMS):** Implementing Use Case UC8 ("Predict remaining km and raise alert") by delivering automated warning notifications when RUL drops below critical thresholds or when oil top-up is needed.
