# Technology Stack & Project Scope Roadmap: Engine Oil Life Monitoring System

**Project Context:** Practical Academic Case Study / Small-Scale Prototype (Foundation for Bachelor Thesis)  
**Student:** Mitrea Vladut-Cristian  
**Supervisor:** Constantin-Renato Ivănescu  
**Faculty:** Faculty of Automation, Computers and Electronics  
**Target Platform:** 2004 Skoda Fabia 1.4L (ISO 9141-2 K-Line OBD-II Interface)  

---

## 1. Technologies Implemented in This Small-Scale Prototype

This prototype implements the complete functional chain (data acquisition $\rightarrow$ mathematical modeling $\rightarrow$ local persistence $\rightarrow$ real-time graphical visualization $\rightarrow$ unit testing):

### A. Automotive Interfacing & Protocol Stack
* **SAE J1979 (OBD-II Standard):** Standard diagnostic parameter polling for Mode 01 PIDs:
  * `0x0C` – Engine RPM (Crankshaft revolutions & mechanical shear)
  * `0x0D` – Vehicle Speed (Distance & transit accumulation)
  * `0x05` – Coolant Temperature (Thermal efficiency & cold condensation flag)
  * `0x04` – Calculated Engine Load (Torque output scaling)
  * `0x1F` – Engine Run Time (Derived duration & city idling stress)
* **ISO 9141-2 / ISO 14230-4:** 10.4 kbps K-Line serial protocols with slow 5-baud initialization native to the 2004 Skoda Fabia ECU.
* **ELM327 Interpreter & AUTOSKY Bluetooth Adapter:** Hardware bridge translating raw K-Line frames into ASCII AT serial commands over virtual COM port (`COM5` at 38,400 baud).

### B. Core Software & Analytical Libraries
* **Python 3:** Core programming language.
* **`python-obd` & `pyserial`:** Serial connection handling, PID request queuing, and frame decoding.
* **`Pint`:** Physical engineering unit conversions.
* **`NumPy` & `Pandas`:** Array math, tabular data structures, and CSV log replay.
* **Physics-Informed Discrete Integrator:**
  * Revolutions increment: $\Delta N = \frac{\omega \cdot \Delta t}{60}$
  * Multi-stress factor: $S = M_{RPM}(\omega) \cdot M_{Temp}(T) \cdot M_{Load}(L)$
  * Incremental damage: $\Delta D = \left(\frac{\Delta N}{N_{ref}}\right) \cdot S$
  * Remaining Useful Life: $RUL(\%) = 100 \cdot (1 - D)$
  * Additive concentration recovery: $H_{new} = \frac{(V_s - \eta \cdot V_{add}) \cdot H_{prior} + (\eta \cdot V_{add}) \cdot 100}{V_s}$

### C. Simulation & Storage
* **MATLAB Scripting (`matlab_drive_cycle_sim.m`):** Vehicle longitudinal dynamics and lumped-capacitance coolant thermal ODE simulation generating standardized CSV logs.
* **SQLite 3 (`oil_monitor.db`):** Embedded ACID-compliant database with WAL (Write-Ahead Logging) and Repository Pattern managing `oil_state`, `trips`, `telemetry_samples`, and `maintenance_events`.

### D. GUI & Verification
* **PyQt6 & PyQtGraph:** Hardware-accelerated desktop dashboard rendering real-time digital gauges, interactive degradation curves, top-up modal, and scenario replay controls.
* **Pytest:** Automated test suite (13 unit and integration tests) verifying math formulas, recovery models, persistence, and extreme stress bounds.
* **Git & GitHub:** Version control tracking project milestones at [`MitreaVladut/Engine-Oil-small-scale`](https://github.com/MitreaVladut/Engine-Oil-small-scale).

---

## 2. Planned Next Steps (Direct Bridge to the Bachelor Thesis)

Rather than adding disconnected complexity, these next steps are focused on naturally scaling this working prototype directly into the final bachelor thesis:

1. **Embedded In-Car Deployment (Raspberry Pi):**
   * Port the Python application to a Raspberry Pi with a small in-dash touchscreen (using either PyQt or lightweight CustomTkinter) running automatically as a `systemd` service on vehicle startup.
2. **Database Scaling (PostgreSQL Migration):**
   * As specified in the initial requirements *(“SQLite (PostgreSQL later)”)*, migrate from the single-file SQLite database to a local or remote PostgreSQL database to handle months of continuous daily commuting data.
3. **Simulink Powertrain Model (Software-in-the-Loop):**
   * Upgrade the standalone `.m` script to a MATLAB Simulink block diagram to simulate engine warm-up and transmission gear selection with higher physical fidelity.
4. **Diagnostic Trouble Code (DTC) Integration:**
   * Implement SAE J1979 Mode 03 / Mode 04 polling to automatically flag engine fault codes (e.g. thermostat stuck open, cylinder misfires) that accelerate oil breakdown.
5. **Real-World Empirical Calibration:**
   * Tune the literature-based degradation coefficients ($M_{RPM}, M_{Temp}, M_{Load}$) using multi-week driving logs from the Skoda Fabia and real oil condition checkpoints.
