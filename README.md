# Algorithmic Engine Oil Life Monitoring (OLM) and Predictive Maintenance System via OBD-II Data Streams

**Academic Project:** Bachelor Thesis - Minimal Design & Implementation Prototype  
**Candidate / Student:** MITREA VLADUT-CRISTIAN  
**Supervisor:** CONSTANTIN-RENATO IVĂNESCU  
**Faculty:** Faculty of Automation, Computers and Electronics  
**Target Platform:** 2004 Skoda Fabia 1.4L (ISO 9141-2 K-Line OBD-II Interface)  

---

## 1. Project Overview

Modern passenger vehicles operating in urban environments experience severe driving conditions—frequent stop-and-go transit, extended idling, and cold-start trips—that accelerate lubricant degradation far beyond simple mileage accumulation. 

The target vehicle is a **2004 Skoda Fabia 1.4L** lacking continuous physical oil quality or dielectric sensors. This project implements a **condition-based, predictive engine oil life monitoring system** that replaces static 10,000–15,000 km oil change countdowns with dynamic, multi-variable mathematical stress modeling.

### Key Capabilities
- **Multi-Source Telemetry Ingestion (Strategy Pattern):** Transparently accepts live ELM327 Bluetooth OBD-II frames, recorded vehicle logs (`car_telemetry_log.csv`), and MATLAB/synthetic drive cycles.
- **Physics-Informed Stress Integrator:** Continuously computes crankshaft revolution accumulation ($\Delta N$), mechanical shear penalties ($M_{RPM}$), thermal condensation/oxidation penalties ($M_{Temp}$), and torque load multipliers ($M_{Load}$).
- **Additive Concentration Recovery:** Recalculates effective oil health upon manual oil top-ups or complete oil changes.
- **Relational Persistence Layer (Repository Pattern):** Stores trips, high-frequency samples, degradation metrics, and maintenance logs in SQLite.
- **Hardware-Accelerated GUI Dashboard (PyQt6 + PyQtGraph):** Renders real-time digital gauges, interactive degradation curves, predictive alerts, and maintenance dialogs.

---

## 2. Mathematical Formulation

### 2.1 Instantaneous Degradation Rate

For each discrete sample interval $\Delta t$ (seconds) with engine speed $\omega$ (RPM):

$$\Delta N = \frac{\omega \cdot \Delta t}{60}$$

The reference revolution budget is:
$$N_{ref} = L_{base} \cdot \rho_{ref}$$
*(For Semi-Synthetic: $10,000\text{ km} \times 2,500\text{ rev/km} = 25.0 \times 10^6\text{ revs}$)*

The composite stress factor $S$ is defined by:
$$S = M_{RPM}(\omega) \cdot M_{Temp}(T) \cdot M_{Load}(L)$$

1. **Mechanical Shear Multiplier ($M_{RPM}$):**
   $$M_{RPM}(\omega) = \begin{cases} 1.0 & \text{if } \omega \le 3500\text{ RPM} \\ 1.0 + \left(\frac{\omega - 3500}{1000}\right)^2 & \text{if } \omega > 3500\text{ RPM} \end{cases}$$

2. **Thermal & Condensation Multiplier ($M_{Temp}$):**
   $$M_{Temp}(T) = \begin{cases} 2.0 & \text{if } T < 70^\circ\text{C} \quad \text{(Cold start / fuel dilution)} \\ 1.0 & \text{if } 70^\circ\text{C} \le T \le 100^\circ\text{C} \quad \text{(Optimal operating window)} \\ 1.5 & \text{if } T > 100^\circ\text{C} \quad \text{(Thermal stress / oxidation)} \end{cases}$$

3. **Engine Load Multiplier ($M_{Load}$):**
   $$M_{Load}(L) = 0.8 + 0.4 \cdot \left(\frac{L\%}{100}\right)$$

### 2.2 Incremental Damage & Remaining Useful Life (RUL)

$$\Delta D = \frac{\Delta N}{N_{ref}} \cdot S$$

$$RUL(T) = \max\left(0.0, \; 100 \cdot (1 - D(T))\right)$$

### 2.3 Additive Concentration Recovery via Top-Up

When fresh oil volume $V_{add}$ is added to an engine with sump capacity $V_s$ (3.7 Liters) and mixing efficiency $\eta$ (0.95):

$$D_{new} = D_{prior} \cdot \left(1 - \eta \cdot \frac{V_{add}}{V_s}\right)$$

$$H_{new} = \frac{(V_s - \eta \cdot V_{add}) \cdot H_{prior} + (\eta \cdot V_{add}) \cdot 100}{V_s}$$

---

## 3. Repository File Structure

```
c:\00 My Stuff\00000000000000000 OBD-Grabber\
├── DESIGN_SPECIFICATION.md          # Complete academic system design specification
├── degradation_engine.py            # Mathematical processing engine & OilConfig dataclasses
├── storage_repository.py            # SQLite database repository layer (trips, samples, events)
├── data_sources.py                  # Strategy pattern data sources (CSV Replay, Live OBD, Sim)
├── drive_cycle_simulator.py         # Physics-based drive-cycle simulator (Cold, Highway, Sport)
├── matlab_drive_cycle_sim.m         # Native MATLAB simulation & CSV export script
├── gui_dashboard.py                 # PyQt6 & PyQtGraph hardware-accelerated interactive dashboard
├── prototype_demonstrator.py        # Automated prototype verification suite (Steps 1, 2, 3)
├── test_rapid_oil_drain.py          # Extreme torture & rapid oil depletion test file (100% -> 0% in ~40s)
├── test_degradation_engine.py       # Comprehensive pytest suite (11 unit/integration tests)
├── rapid_oil_drain_log.csv          # Generated extreme stress telemetry log (24,000 RPM overspeed)
├── car_logger.py                    # Standalone hardware OBD-II polling logger for COM5
├── car_telemetry_log.csv            # Real vehicle telemetry log from the 2004 Skoda Fabia (1,820 rows)
├── matlab_telemetry_cold_short_trip.csv  # Generated Cold Short-Trip simulation dataset
├── matlab_telemetry_steady_highway.csv   # Generated Steady Highway simulation dataset
└── matlab_telemetry_aggressive.csv       # Generated High-RPM Aggressive driving dataset
```

---

## 4. Execution & Quick Start

### 4.1 Running the Interactive Desktop Dashboard
Launch the graphical dashboard with real-time gauges, live RUL tracking, and scenario replay:
```bash
python gui_dashboard.py
```
- Select data source from the dropdown (Real Car CSV, Cold Short-Trip, Steady Highway, or Live OBD).
- Adjust the replay speed slider (1x up to 50x).
- Click **"▶ Start Stream / Trip"** to observe real-time degradation.
- Click **"💧 Log Oil Top-Up"** to test live additive replenishment.

### 4.2 Running the Automated Prototype Demonstration
Executes the three validation steps specified in Section 6 of the academic project report:
```bash
python prototype_demonstrator.py
```
- **Step 1:** Unified replay of `car_telemetry_log.csv` and MATLAB cycle.
- **Step 2:** Quantitative comparison showing cold short-trip degrading oil at **3.17x the rate per km** of steady highway driving.
- **Step 3:** Verifies oil top-up formula (RUL rising from 70.0% to 77.7% upon 1.0L top-up).

### 4.3 Running the Rapid Oil Drain Extreme Test
Simulates physically extreme, hypothetical stress conditions (24,000 RPM overspeed, 138°C coolant boiling, 100% load) that exhaust 100% of oil life in ~40 seconds:
```bash
python test_rapid_oil_drain.py
```
*(Also selectable directly inside the GUI Dashboard dropdown as **"🔥 Extreme Torture Test (Rapid Drain to 0%)"**)*

### 4.4 Running the Unit Test Suite
Verifies all mathematical models, NFRs, and persistence logic:
```bash
python -m pytest -v
```

### 4.4 Hardware Connection on Vehicle
To log live data from the 2004 Skoda Fabia using the AUTOSKY Bluetooth OBD-II adapter:
```bash
python car_logger.py
```
*(Configured for COM5, baudrate 38400, protocol 3 ISO 9141-2 with protocol 5 fallback)*
