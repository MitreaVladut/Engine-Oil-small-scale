"""
gui_dashboard.py
----------------
PyQt6 & PyQtGraph Interactive Desktop Dashboard for the Algorithmic Engine Oil Life Monitoring System.
Target vehicle: 2004 Skoda Fabia 1.4L (ISO 9141-2 K-Line testbed).

Implements:
- FR1, FR2, FR3 (live telemetry ingestion & display)
- FR4 (continuous RUL % degradation visualization)
- FR5 (interactive oil top-up and oil change logging)
- FR6 (historical trips, persistence, and chart rendering)
- Architecture: Section 4.1 MVP / Observer pattern with Qt Signals & Slots
"""

import sys
import os
import time
from datetime import datetime
from typing import Optional, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QComboBox, QSlider, QProgressBar,
    QGroupBox, QDialog, QDoubleSpinBox, QFormLayout, QMessageBox,
    QFrame, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QPalette, QLinearGradient, QBrush

import pyqtgraph as pg

from degradation_engine import OilConfig, TelemetrySample, DegradationEngine, DegradationResult
from storage_repository import StorageRepository
from data_sources import CSVReplayDataSource, RealOBDDataSource, GeneratorDataSource, IDataSource
from drive_cycle_simulator import DriveCycleSimulator


class TopUpDialog(QDialog):
    """Modal dialog allowing the driver to log an oil top-up or full replacement."""

    def __init__(self, current_rul: float, sump_capacity: float = 3.7, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Oil Top-Up / Maintenance")
        self.setFixedWidth(380)
        self.current_rul = current_rul
        self.sump_capacity = sump_capacity

        layout = QVBoxLayout(self)

        info_lbl = QLabel(f"Current Sump Capacity: <b>{self.sump_capacity:.1f} Liters</b><br>"
                          f"Current Oil RUL: <b>{self.current_rul:.1f}%</b>")
        info_lbl.setStyleSheet("color: #e2e8f0; font-size: 13px; margin-bottom: 8px;")
        layout.addWidget(info_lbl)

        form = QFormLayout()

        self.spin_volume = QDoubleSpinBox()
        self.spin_volume.setRange(0.1, sump_capacity)
        self.spin_volume.setSingleStep(0.25)
        self.spin_volume.setValue(1.0)
        self.spin_volume.setSuffix(" Liters")
        self.spin_volume.setStyleSheet("background: #1e293b; color: white; padding: 4px; font-size: 13px;")
        form.addRow("Fresh Oil Volume:", self.spin_volume)

        self.combo_grade = QComboBox()
        self.combo_grade.addItems(["5W-40 Synthetic", "10W-40 Semi-Synthetic", "15W-40 Mineral"])
        self.combo_grade.setStyleSheet("background: #1e293b; color: white; padding: 4px; font-size: 13px;")
        form.addRow("Oil Grade / Type:", self.combo_grade)

        self.spin_efficiency = QDoubleSpinBox()
        self.spin_efficiency.setRange(0.50, 1.00)
        self.spin_efficiency.setSingleStep(0.05)
        self.spin_efficiency.setValue(0.95)
        self.spin_efficiency.setStyleSheet("background: #1e293b; color: white; padding: 4px; font-size: 13px;")
        form.addRow("Mixing Efficiency (η):", self.spin_efficiency)

        self.lbl_preview = QLabel()
        self.lbl_preview.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 14px; margin: 10px 0;")
        form.addRow("Expected New RUL:", self.lbl_preview)

        layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("Confirm Top-Up")
        self.btn_apply.setStyleSheet("background: #10b981; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("background: #475569; color: white; padding: 8px 16px; border-radius: 4px;")

        self.btn_apply.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_apply)
        layout.addLayout(btn_layout)

        self.spin_volume.valueChanged.connect(self.update_preview)
        self.spin_efficiency.valueChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        v_add = self.spin_volume.value()
        eta = self.spin_efficiency.value()
        old_h = self.current_rul
        v_s = self.sump_capacity
        new_h = ((v_s - eta * v_add) * old_h + (eta * v_add) * 100.0) / v_s
        new_h = min(100.0, max(old_h, new_h))
        self.lbl_preview.setText(f"{new_h:.1f}% (+{new_h - old_h:.1f}%)")

    def get_values(self):
        return {
            "volume": self.spin_volume.value(),
            "grade": self.combo_grade.currentText(),
            "efficiency": self.spin_efficiency.value()
        }


class OilLifeDashboard(QMainWindow):
    """
    Main Automotive Telemetry & Predictive Maintenance GUI window.
    """

    def __init__(self, db_path: str = "oil_monitor.db"):
        super().__init__()
        self.setWindowTitle("Skoda Fabia 1.4L - Algorithmic Engine Oil Life Monitoring System")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 700)

        # Core Components
        self.repository = StorageRepository(db_path=db_path)
        persisted_state = self.repository.get_or_create_oil_state()
        config = OilConfig(
            oil_type=persisted_state["oil_type"],
            base_mileage_km=persisted_state["base_mileage_km"],
            sump_capacity_liters=persisted_state["sump_capacity_liters"]
        )
        self.engine = DegradationEngine(config=config, initial_damage=persisted_state["cumulative_damage"])
        self.engine.cumulative_revolutions = persisted_state["cumulative_revolutions"]
        self.engine.cumulative_distance_km = persisted_state["total_distance_km"]
        self.engine.cumulative_engine_seconds = persisted_state["total_engine_hours"] * 3600.0

        self.data_source: Optional[IDataSource] = None
        self.current_trip_id: Optional[int] = None

        # Data series for real-time charting
        self.history_time_steps: List[int] = []
        self.history_rul: List[float] = []
        self.history_coolant: List[float] = []
        self.history_stress: List[float] = []
        self.step_counter = 0

        # UI Timer for asynchronous polling / playback loop
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._on_tick)

        self._setup_dark_theme()
        self._init_ui()

    def _setup_dark_theme(self):
        """Applies a sleek automotive dashboard dark styling."""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(15, 23, 42))        # #0f172a
        palette.setColor(QPalette.ColorRole.WindowText, QColor(241, 245, 249)) # #f1f5f9
        palette.setColor(QPalette.ColorRole.Base, QColor(30, 41, 59))          # #1e293b
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(51, 65, 85))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(15, 23, 42))
        palette.setColor(QPalette.ColorRole.Text, QColor(241, 245, 249))
        palette.setColor(QPalette.ColorRole.Button, QColor(30, 41, 59))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(241, 245, 249))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(14, 165, 233))   # #0ea5e9
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header Banner
        main_layout.addLayout(self._create_header_banner())

        # 2. Hero KPI Cards (Live Gauges & RUL Health)
        main_layout.addLayout(self._create_kpi_cards())

        # 3. Chart & Analytics Section
        main_layout.addWidget(self._create_chart_panel(), stretch=1)

        # 4. Control Toolbar & Source Selector
        main_layout.addLayout(self._create_control_toolbar())

    def _create_header_banner(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        
        lbl_title = QLabel("Algorithmic Engine Oil Life Monitoring (OLM) System")
        lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #38bdf8;")
        lbl_sub = QLabel("Target: 2004 Skoda Fabia 1.4L | Protocol: ISO 9141-2 K-Line | Method: Multi-Stress Integral")
        lbl_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box)

        header.addStretch()

        # Alert Badge
        self.lbl_alert_badge = QLabel("STATUS: NORMAL")
        self.lbl_alert_badge.setStyleSheet(
            "background: #065f46; color: #34d399; font-weight: bold; "
            "padding: 6px 14px; border-radius: 6px; font-size: 13px;"
        )
        header.addWidget(self.lbl_alert_badge)

        return header

    def _create_kpi_cards(self) -> QHBoxLayout:
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        # Card 1: Remaining Useful Life (RUL %)
        card_rul = QFrame()
        card_rul.setStyleSheet("background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155;")
        c1_layout = QVBoxLayout(card_rul)
        c1_layout.setContentsMargins(8, 8, 8, 8)
        
        lbl_c1_title = QLabel("REMAINING OIL LIFE (RUL)")
        lbl_c1_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        self.lbl_rul_val = QLabel(f"{self.engine.rul_percent:.1f}%")
        self.lbl_rul_val.setStyleSheet("color: #10b981; font-size: 32px; font-weight: bold;")
        
        self.bar_rul = QProgressBar()
        self.bar_rul.setRange(0, 100)
        self.bar_rul.setValue(int(self.engine.rul_percent))
        self.bar_rul.setTextVisible(False)
        self.bar_rul.setFixedHeight(10)
        self.bar_rul.setStyleSheet("""
            QProgressBar { background: #334155; border-radius: 5px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #38bdf8); border-radius: 5px; }
        """)

        self.lbl_est_distance = QLabel(f"Forecast: ~{self.engine.predict_remaining_km():.0f} km")
        self.lbl_est_distance.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-top: 4px;")

        c1_layout.addWidget(lbl_c1_title)
        c1_layout.addWidget(self.lbl_rul_val)
        c1_layout.addWidget(self.bar_rul)
        c1_layout.addWidget(self.lbl_est_distance)
        cards_layout.addWidget(card_rul, stretch=2)

        # Card 2: Engine Speed (RPM)
        card_rpm = QFrame()
        card_rpm.setStyleSheet("background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155;")
        c2_layout = QVBoxLayout(card_rpm)
        lbl_c2_title = QLabel("ENGINE SPEED (RPM)")
        lbl_c2_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        self.lbl_rpm_val = QLabel("0 RPM")
        self.lbl_rpm_val.setStyleSheet("color: #f8fafc; font-size: 28px; font-weight: bold;")
        self.lbl_rpm_sub = QLabel("Shear Factor: 1.00x")
        self.lbl_rpm_sub.setStyleSheet("color: #64748b; font-size: 12px;")
        c2_layout.addWidget(lbl_c2_title)
        c2_layout.addWidget(self.lbl_rpm_val)
        c2_layout.addWidget(self.lbl_rpm_sub)
        cards_layout.addWidget(card_rpm, stretch=1)

        # Card 3: Coolant Temperature
        card_temp = QFrame()
        card_temp.setStyleSheet("background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155;")
        c3_layout = QVBoxLayout(card_temp)
        lbl_c3_title = QLabel("COOLANT TEMP")
        lbl_c3_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        self.lbl_temp_val = QLabel("-- °C")
        self.lbl_temp_val.setStyleSheet("color: #38bdf8; font-size: 28px; font-weight: bold;")
        self.lbl_temp_sub = QLabel("Thermal: Normal (1.0x)")
        self.lbl_temp_sub.setStyleSheet("color: #64748b; font-size: 12px;")
        c3_layout.addWidget(lbl_c3_title)
        c3_layout.addWidget(self.lbl_temp_val)
        c3_layout.addWidget(self.lbl_temp_sub)
        cards_layout.addWidget(card_temp, stretch=1)

        # Card 4: Vehicle Speed & Load
        card_speed = QFrame()
        card_speed.setStyleSheet("background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155;")
        c4_layout = QVBoxLayout(card_speed)
        lbl_c4_title = QLabel("SPEED & LOAD")
        lbl_c4_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        self.lbl_speed_val = QLabel("0.0 km/h")
        self.lbl_speed_val.setStyleSheet("color: #f8fafc; font-size: 28px; font-weight: bold;")
        self.lbl_load_sub = QLabel("Load: 0.0%")
        self.lbl_load_sub.setStyleSheet("color: #64748b; font-size: 12px;")
        c4_layout.addWidget(lbl_c4_title)
        c4_layout.addWidget(self.lbl_speed_val)
        c4_layout.addWidget(self.lbl_load_sub)
        cards_layout.addWidget(card_speed, stretch=1)

        # Card 5: Composite Stress Factor
        card_stress = QFrame()
        card_stress.setStyleSheet("background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155;")
        c5_layout = QVBoxLayout(card_stress)
        lbl_c5_title = QLabel("COMPOSITE STRESS (S)")
        lbl_c5_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        self.lbl_stress_val = QLabel("1.00x")
        self.lbl_stress_val.setStyleSheet("color: #fbbf24; font-size: 28px; font-weight: bold;")
        self.lbl_stress_sub = QLabel("S = f_rpm·f_temp·f_load")
        self.lbl_stress_sub.setStyleSheet("color: #64748b; font-size: 12px;")
        c5_layout.addWidget(lbl_c5_title)
        c5_layout.addWidget(self.lbl_stress_val)
        c5_layout.addWidget(self.lbl_stress_sub)
        cards_layout.addWidget(card_stress, stretch=1)

        return cards_layout

    def _create_chart_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Configure pyqtgraph styling
        pg.setConfigOption('background', '#0b1120')
        pg.setConfigOption('foreground', '#94a3b8')

        self.plot_widget = pg.PlotWidget(title="Real-Time Oil Degradation & Telemetry Dynamics")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.addLegend(offset=(10, 10))

        # Curves
        self.curve_rul = self.plot_widget.plot(
            pen=pg.mkPen(color='#10b981', width=3),
            name="Remaining Useful Life (RUL %)"
        )
        self.curve_temp = self.plot_widget.plot(
            pen=pg.mkPen(color='#38bdf8', width=2, style=Qt.PenStyle.DashLine),
            name="Coolant Temp (°C)"
        )
        self.curve_stress = self.plot_widget.plot(
            pen=pg.mkPen(color='#fbbf24', width=2),
            name="Stress Multiplier (S x 10)"
        )

        layout.addWidget(self.plot_widget)
        return panel

    def _create_control_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        # Data Source Selector
        lbl_src = QLabel("Data Source:")
        lbl_src.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        toolbar.addWidget(lbl_src)

        self.combo_source = QComboBox()
        self.combo_source.addItem("Real Car Telemetry (car_telemetry_log.csv)", "REAL_CSV")
        self.combo_source.addItem("MATLAB Sim: Cold Short-Trip (High Stress)", "SIM_COLD")
        self.combo_source.addItem("MATLAB Sim: Steady Highway (Low Stress)", "SIM_HWY")
        self.combo_source.addItem("MATLAB Sim: Aggressive High-RPM", "SIM_AGG")
        self.combo_source.addItem("🔥 Extreme Torture Test (Rapid Drain to 0%)", "SIM_TORTURE")
        self.combo_source.addItem("Live OBD-II Hardware (COM5, ISO 9141-2)", "LIVE_OBD")
        self.combo_source.setStyleSheet("background: #1e293b; color: white; padding: 6px; border-radius: 4px; min-width: 280px;")
        toolbar.addWidget(self.combo_source)

        # Replay Speed
        lbl_spd = QLabel("Replay Speed:")
        lbl_spd.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        toolbar.addWidget(lbl_spd)

        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(1, 50)
        self.slider_speed.setValue(5)
        self.slider_speed.setFixedWidth(100)
        self.lbl_speed_indicator = QLabel("5x")
        self.slider_speed.valueChanged.connect(lambda v: self.lbl_speed_indicator.setText(f"{v}x"))
        toolbar.addWidget(self.slider_speed)
        toolbar.addWidget(self.lbl_speed_indicator)

        # Play / Pause
        self.btn_play = QPushButton("▶ Start Stream / Trip")
        self.btn_play.setStyleSheet("background: #0284c7; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px;")
        self.btn_play.clicked.connect(self._toggle_stream)
        toolbar.addWidget(self.btn_play)

        toolbar.addStretch()

        # Action: Log Oil Top-Up
        self.btn_topup = QPushButton("💧 Log Oil Top-Up")
        self.btn_topup.setStyleSheet("background: #059669; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        self.btn_topup.clicked.connect(self._open_topup_dialog)
        toolbar.addWidget(self.btn_topup)

        # Action: Full Oil Change
        self.btn_change = QPushButton("🔄 Full Oil Change")
        self.btn_change.setStyleSheet("background: #d97706; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        self.btn_change.clicked.connect(self._handle_full_oil_change)
        toolbar.addWidget(self.btn_change)

        return toolbar

    def _toggle_stream(self):
        if self.poll_timer.isActive():
            # Stop streaming
            self.poll_timer.stop()
            if self.data_source:
                self.data_source.stop()
            self._close_current_trip()
            self.btn_play.setText("▶ Start Stream / Trip")
            self.btn_play.setStyleSheet("background: #0284c7; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px;")
        else:
            # Start streaming
            selected_key = self.combo_source.currentData()
            self._init_data_source(selected_key)
            if not self.data_source or not self.data_source.start():
                QMessageBox.warning(self, "Source Error", "Failed to initialize the selected telemetry source.")
                return

            # Start trip in SQLite
            source_label = self.combo_source.currentText()
            self.current_trip_id = self.repository.start_trip(
                source_type=selected_key,
                scenario_name=source_label,
                initial_rul=self.engine.rul_percent
            )

            # Set timer delay based on slider speed
            speed_factor = self.slider_speed.value()
            interval_ms = max(10, int(1000 / speed_factor))
            self.poll_timer.start(interval_ms)

            self.btn_play.setText("⏸ Pause Stream")
            self.btn_play.setStyleSheet("background: #dc2626; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px;")

    def _init_data_source(self, key: str):
        if key == "REAL_CSV":
            csv_path = "car_telemetry_log.csv"
            self.data_source = CSVReplayDataSource(csv_filepath=csv_path, loop=False)
        elif key == "SIM_COLD":
            sim = DriveCycleSimulator(ambient_temp_c=18.0)
            cold_samples = sim.generate_cold_short_trip(duration_seconds=600)
            self.data_source = GeneratorDataSource(lambda: (s for s in cold_samples), name="Cold Short-Trip")
        elif key == "SIM_HWY":
            sim = DriveCycleSimulator()
            hwy_samples = sim.generate_steady_highway(duration_seconds=600)
            self.data_source = GeneratorDataSource(lambda: (s for s in hwy_samples), name="Steady Highway")
        elif key == "SIM_AGG":
            sim = DriveCycleSimulator()
            agg_samples = sim.generate_aggressive_high_stress(duration_seconds=600)
            self.data_source = GeneratorDataSource(lambda: (s for s in agg_samples), name="Aggressive High Stress")
        elif key == "SIM_TORTURE":
            sim = DriveCycleSimulator()
            torture_samples = sim.generate_catastrophic_torture_cycle(duration_seconds=120)
            self.data_source = GeneratorDataSource(lambda: (s for s in torture_samples), name="Extreme Torture Test")
        elif key == "LIVE_OBD":
            self.data_source = RealOBDDataSource(port_name="COM5", baudrate=38400)

    def _on_tick(self):
        if not self.data_source or not self.data_source.is_active():
            self._toggle_stream()
            return

        sample = self.data_source.read_next_sample()
        if sample is None:
            # End of stream
            self._toggle_stream()
            return

        # Process through degradation engine
        result = self.engine.process_sample(sample)

        # Log into database
        if self.current_trip_id is not None:
            self.repository.log_sample(self.current_trip_id, sample, result)

        # Update GUI Readouts
        self._update_kpis(sample, result)

        # Append to plot curves
        self.step_counter += 1
        self.history_time_steps.append(self.step_counter)
        self.history_rul.append(result.rul_percent)
        self.history_coolant.append(sample.coolant_temp_c)
        self.history_stress.append(result.stress_factor * 10.0)

        # Keep rolling window of last 500 samples
        if len(self.history_time_steps) > 500:
            self.history_time_steps.pop(0)
            self.history_rul.pop(0)
            self.history_coolant.pop(0)
            self.history_stress.pop(0)

        self.curve_rul.setData(self.history_time_steps, self.history_rul)
        self.curve_temp.setData(self.history_time_steps, self.history_coolant)
        self.curve_stress.setData(self.history_time_steps, self.history_stress)

    def _update_kpis(self, sample: TelemetrySample, result: DegradationResult):
        # 1. RUL
        rul = result.rul_percent
        self.lbl_rul_val.setText(f"{rul:.2f}%")
        self.bar_rul.setValue(int(rul))

        # Dynamic color coding for RUL
        if rul > 30.0:
            color = "#10b981"
            self.lbl_alert_badge.setText("STATUS: HEALTHY")
            self.lbl_alert_badge.setStyleSheet("background: #065f46; color: #34d399; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        elif rul > 15.0:
            color = "#f59e0b"
            self.lbl_alert_badge.setText("STATUS: SERVICE DUE")
            self.lbl_alert_badge.setStyleSheet("background: #78350f; color: #fbbf24; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        else:
            color = "#ef4444"
            self.lbl_alert_badge.setText("STATUS: CRITICAL EXHAUSTION")
            self.lbl_alert_badge.setStyleSheet("background: #7f1d1d; color: #f87171; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        self.lbl_rul_val.setStyleSheet(f"color: {color}; font-size: 32px; font-weight: bold;")

        # Forecast km
        self.lbl_est_distance.setText(f"Forecast: ~{self.engine.predict_remaining_km():.0f} km")

        # 2. RPM
        self.lbl_rpm_val.setText(f"{sample.rpm:.0f} RPM")
        rpm_color = "#ef4444" if sample.rpm > 3500 else "#f8fafc"
        self.lbl_rpm_val.setStyleSheet(f"color: {rpm_color}; font-size: 28px; font-weight: bold;")
        self.lbl_rpm_sub.setText(f"Shear Factor: {result.f_rpm:.2f}x")

        # 3. Coolant Temp
        self.lbl_temp_val.setText(f"{sample.coolant_temp_c:.1f} °C")
        if sample.coolant_temp_c < 70.0:
            temp_desc = "Cold (Condensation 2.0x)"
            temp_color = "#38bdf8"
        elif sample.coolant_temp_c <= 100.0:
            temp_desc = "Optimal (1.0x)"
            temp_color = "#10b981"
        else:
            temp_desc = "Overheating (Oxidation 1.5x)"
            temp_color = "#ef4444"
        self.lbl_temp_val.setStyleSheet(f"color: {temp_color}; font-size: 28px; font-weight: bold;")
        self.lbl_temp_sub.setText(temp_desc)

        # 4. Speed & Load
        self.lbl_speed_val.setText(f"{sample.speed_kmh:.1f} km/h")
        self.lbl_load_sub.setText(f"Load: {sample.engine_load_pct:.1f}% (x{result.f_load:.2f})")

        # 5. Composite Stress
        self.lbl_stress_val.setText(f"{result.stress_factor:.2f}x")
        self.lbl_stress_sub.setText(f"Revs Acc: {self.engine.cumulative_revolutions:,.0f}")

    def _close_current_trip(self):
        if self.current_trip_id is not None:
            self.repository.end_trip(
                trip_id=self.current_trip_id,
                final_rul=self.engine.rul_percent,
                distance_km=self.engine.cumulative_distance_km,
                duration_seconds=self.engine.cumulative_engine_seconds
            )
            self.repository.save_oil_state(self.engine)
            self.current_trip_id = None

    def _open_topup_dialog(self):
        dialog = TopUpDialog(
            current_rul=self.engine.rul_percent,
            sump_capacity=self.engine.config.sump_capacity_liters,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            vals = dialog.get_values()
            res = self.engine.apply_top_up(
                volume_liters=vals["volume"],
                mixing_efficiency=vals["efficiency"]
            )
            # Log in database
            self.repository.log_maintenance_event(
                event_type="TOP_UP",
                volume_liters=vals["volume"],
                oil_grade=vals["grade"],
                mixing_efficiency=vals["efficiency"],
                rul_before=res["prior_rul"],
                rul_after=res["new_rul"],
                notes=f"Added {vals['volume']}L fresh oil"
            )
            self.repository.save_oil_state(self.engine)

            # Update charts & GUI
            self.lbl_rul_val.setText(f"{self.engine.rul_percent:.2f}%")
            self.bar_rul.setValue(int(self.engine.rul_percent))
            self.step_counter += 1
            self.history_time_steps.append(self.step_counter)
            self.history_rul.append(self.engine.rul_percent)
            self.history_coolant.append(self.history_coolant[-1] if self.history_coolant else 85.0)
            self.history_stress.append(10.0)
            self.curve_rul.setData(self.history_time_steps, self.history_rul)

            QMessageBox.information(
                self,
                "Oil Replenishment Logged",
                f"Successfully logged {vals['volume']} L top-up!\n"
                f"Prior RUL: {res['prior_rul']:.1f}%\n"
                f"New RUL: {res['new_rul']:.1f}%\n"
                f"Additive Gain: +{res['rul_gain']:.1f}%"
            )

    def _handle_full_oil_change(self):
        reply = QMessageBox.question(
            self,
            "Confirm Full Oil Change",
            "Are you sure you want to log a complete oil change?\n"
            "This will drain all old oil, clear accumulated damage, and restore RUL to 100%.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            prior_rul = self.engine.rul_percent
            self.engine.apply_full_oil_change()
            self.repository.log_maintenance_event(
                event_type="FULL_CHANGE",
                volume_liters=self.engine.config.sump_capacity_liters,
                oil_grade=self.engine.config.oil_type,
                mixing_efficiency=1.0,
                rul_before=prior_rul,
                rul_after=100.0,
                notes="Complete crankcase oil drain and fresh refill"
            )
            self.repository.save_oil_state(self.engine)

            self.lbl_rul_val.setText("100.00%")
            self.bar_rul.setValue(100)
            self.step_counter += 1
            self.history_time_steps.append(self.step_counter)
            self.history_rul.append(100.0)
            self.history_coolant.append(self.history_coolant[-1] if self.history_coolant else 85.0)
            self.history_stress.append(10.0)
            self.curve_rul.setData(self.history_time_steps, self.history_rul)

            QMessageBox.information(self, "Oil Change Complete", "Oil state successfully reset to 100.0% RUL.")

    def closeEvent(self, event):
        if self.poll_timer.isActive():
            self.poll_timer.stop()
        if self.data_source:
            self.data_source.stop()
        self._close_current_trip()
        event.accept()


def launch_dashboard():
    app = QApplication(sys.argv)
    window = OilLifeDashboard()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_dashboard()
