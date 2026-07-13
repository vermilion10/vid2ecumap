#!/usr/bin/env python3
"""
ECU MAPPER RT — Desktop Edition
A Qt (PySide6) desktop app that turns any local video into a live,
adjustable heatmap "tuning table" with real-time 2D/3D surface graphs,
styled after classic ECU calibration software (SXTune / TunerPro-esque).

No video is bundled with this app. Load your own file via the toolbar's
folder icon (File > Open Calibration/Video also works). Everything runs
100% locally.
"""
import sys
import time
import numpy as np
import cv2

import pyqtgraph as pg
import pyqtgraph.opengl as gl

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QImage, QPainter, QColor, QFont, QAction, QActionGroup, QPen,
    QFontMetrics, QPalette, QIcon, QPixmap, QPolygonF
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QSpinBox, QCheckBox, QFileDialog, QStatusBar,
    QToolBar, QToolButton, QGroupBox, QFormLayout, QMessageBox, QDialog,
    QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QDockWidget, QSplitter,
    QFrame, QSizePolicy
)

pg.setConfigOption('background', '#ffffff')
pg.setConfigOption('foreground', '#333333')
pg.setConfigOptions(antialias=True)

APP_TITLE = "ECU MAPPER RT"

MAP_TYPES = {
    "afr":      {"title": "AFR Target",       "min": 10.0, "max": 18.0, "dec": 1,
                 "desc": "Target air/fuel ratio as a function of engine speed and load. "
                          "Lower values (rich) toward the top-left, higher values (lean) "
                          "toward the bottom-right of the underlying frame data."},
    "fuel":     {"title": "Main Injection Quantity", "min": 60.0, "max": 140.0, "dec": 1,
                 "desc": "Base fuel map (VE / injector pulse-width surface) selected by map "
                          "switch. Calculates fuel injection pulse width as a function of "
                          "engine speed and load, expressed as a percentage of the maximum "
                          "injection pulse-width variable."},
    "timing":   {"title": "Ignition Correction Factors", "min": -10.0, "max": 46.0, "dec": 0,
                 "desc": "Trim correction applied on top of the base spark map, driven here "
                          "by frame-to-frame motion in the loaded datalog source."},
    "boost":    {"title": "Boost Control",    "min": -5.0, "max": 25.0, "dec": 1,
                 "desc": "Target boost pressure surface across the operating range."},
    "spark":    {"title": "Main Spark Advance", "min": 5.0, "max": 75.0, "dec": 1,
                 "desc": "Base ignition timing map. Values represent degrees of advance "
                          "before top dead centre across the engine speed / load range."},
    "injector": {"title": "Fuel Correction Factors", "min": 80.0, "max": 120.0, "dec": 1,
                 "desc": "Multiplicative trim applied to the base injection map, typically "
                          "used to correct for injector flow variance across banks."},
}

# Pastel table palette (default)
LUT_PASTEL = np.array([[127,134,224],[127,201,196],[165,204,122],[224,184,110],[224,119,110]], dtype=np.float32)
# Vivid rainbow ("jet"-like) palette
LUT_VIVID  = np.array([[30,40,170],[20,160,210],[40,190,60],[230,220,30],[220,40,30]], dtype=np.float32)
# Thermal palette
LUT_THERMAL = np.array([[10,10,40],[120,10,120],[220,60,20],[250,170,20],[255,250,200]], dtype=np.float32)
STOP_T = np.array([0.0, 0.25, 0.5, 0.75, 1.0])


def build_lut(stops, n=256):
    ts = np.linspace(0, 1, n)
    r = np.interp(ts, STOP_T, stops[:, 0])
    g = np.interp(ts, STOP_T, stops[:, 1])
    b = np.interp(ts, STOP_T, stops[:, 2])
    return np.stack([r, g, b], axis=1).astype(np.uint8)


TABLE_LUTS = {
    "Pastel": build_lut(LUT_PASTEL),
    "Vivid": build_lut(LUT_VIVID),
    "Thermal": build_lut(LUT_THERMAL),
}
JET_LUT = build_lut(LUT_VIVID)  # used for the 3D surface + 2D lines


def rpm_for_col(c, cols):
    t = c / (cols - 1) if cols > 1 else 0
    return int(round((500 + t * (8000 - 500)) / 50) * 50)


def load_for_row(r, rows):
    t = r / (rows - 1) if rows > 1 else 0
    return int(round((20 + t * (250 - 20)) / 5) * 5)


def make_swatch_icon(qcolor, size=15):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(0, 0, 0, 60))
    p.setBrush(qcolor)
    p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    p.end()
    return QIcon(pix)


def make_symbol_icon(kind, color="#333333", size=16):
    """Small drawn glyphs for the toolbar buttons"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.4)
    p.setPen(pen)
    p.setBrush(QColor(color))
    m = size / 2
    if kind == "folder":
        p.setBrush(QColor("#e8b93f"))
        p.setPen(QColor("#a8801f"))
        p.drawRect(2, 6, size - 4, size - 8)
        p.drawRect(2, 4, size * 0.5, 3)
    elif kind == "save":
        p.setBrush(QColor("#5c8fd6"))
        p.setPen(QColor("#2f5fb0"))
        p.drawRect(2, 2, size - 4, size - 4)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(5, 8, size - 10, size - 10)
    elif kind == "minus":
        p.drawLine(3, m, size - 3, m)
    elif kind == "plus":
        p.drawLine(3, m, size - 3, m)
        p.drawLine(m, 3, m, size - 3)
    elif kind == "star":
        p.drawText(pix.rect(), Qt.AlignCenter, "*")
    elif kind == "zero":
        p.drawEllipse(3, 3, size - 6, size - 6)
    elif kind == "undo":
        p.drawArc(3, 3, size - 6, size - 6, 60 * 16, 250 * 16)
    p.end()
    return QIcon(pix)


class HeatmapWidget(QWidget):
    """Renders the current grid as a colour-coded tuning table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 220)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor("#ffffff"))
        self.setPalette(pal)

        self.rows = 0
        self.cols = 0
        self.rgb = None
        self.values = None
        self.dec = 1
        self.show_values = True
        self.show_axis = True

    def set_frame(self, rgb, values, dec):
        self.rgb = rgb
        self.values = values
        self.dec = dec
        self.rows, self.cols = rgb.shape[0], rgb.shape[1]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if self.rgb is None or self.cols == 0 or self.rows == 0:
            painter.setPen(QColor("#8a8a8a"))
            painter.setFont(QFont("Sans Serif", 10))
            painter.drawText(self.rect(), Qt.AlignCenter,
                              "No datalog loaded")
            painter.end()
            return

        left_margin = 48 if self.show_axis else 4
        top_margin = 20 if self.show_axis else 4
        avail_w = max(10, self.width() - left_margin - 6)
        avail_h = max(10, self.height() - top_margin - 6)
        cell_w = avail_w / self.cols
        cell_h = avail_h / self.rows

        img = QImage(self.rgb.data, self.cols, self.rows, 3 * self.cols,
                      QImage.Format_RGB888).copy()
        target = QRectF(left_margin, top_margin, avail_w, avail_h)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(target, img)

        dense = (self.rows * self.cols) > 4000
        show_text = self.show_values and cell_w >= 15 and cell_h >= 12 and not dense

        if show_text:
            painter.setPen(QPen(QColor(185, 195, 209), 1))
            for c in range(self.cols + 1):
                x = left_margin + c * cell_w
                painter.drawLine(x, top_margin, x, top_margin + avail_h)
            for r in range(self.rows + 1):
                y = top_margin + r * cell_h
                painter.drawLine(left_margin, y, left_margin + avail_w, y)

            font = QFont("Consolas" if sys.platform.startswith("win") else "Monospace")
            font.setPointSizeF(max(5.5, min(cell_h * 0.42, cell_w * 0.24, 11)))
            painter.setFont(font)
            painter.setPen(QColor("#1a1f26"))
            for r in range(self.rows):
                for c in range(self.cols):
                    txt = f"{self.values[r, c]:.{self.dec}f}"
                    cell_rect = QRectF(left_margin + c * cell_w, top_margin + r * cell_h, cell_w, cell_h)
                    painter.drawText(cell_rect, Qt.AlignCenter, txt)

        if self.show_axis:
            painter.setPen(QColor("#3f6ea8"))
            painter.setBrush(QColor("#3f6ea8"))
            painter.drawRect(QRectF(0, 0, left_margin, top_margin))
            painter.drawRect(QRectF(left_margin, 0, avail_w, top_margin))
            painter.drawRect(QRectF(0, top_margin, left_margin, avail_h))
            painter.setPen(QColor(255, 255, 255))
            small = QFont("Consolas" if sys.platform.startswith("win") else "Monospace")
            small.setPointSizeF(7.5)
            painter.setFont(small)
            fm = QFontMetrics(small)
            label_w = fm.horizontalAdvance("0000") + 5
            col_step = max(1, int(np.ceil(label_w / max(cell_w, 1))))
            for c in range(0, self.cols, col_step):
                cell_rect = QRectF(left_margin + c * cell_w, 2, cell_w * col_step, top_margin - 4)
                painter.drawText(cell_rect, Qt.AlignCenter, str(rpm_for_col(c, self.cols)))
            row_step = max(1, int(np.ceil(fm.height() / max(cell_h, 1))))
            for r in range(0, self.rows, row_step):
                cell_rect = QRectF(2, top_margin + r * cell_h, left_margin - 6, cell_h * row_step)
                painter.drawText(cell_rect, Qt.AlignCenter, str(load_for_row(r, self.rows)))
        painter.end()


class SiteTargetGauge(QWidget):
    """Small semicircular needle gauge. Driven by render FPS relative to a 0-10 scale"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(90)
        self.value = 0.0  # 0..10
        self.target = 6.0

    def set_value(self, v):
        self.value = max(0.0, min(10.0, v))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy, rad = w / 2, h - 12, min(w / 2 - 10, h - 24)
        gauge_pen = QPen(QColor("#8a94a3"))
        gauge_pen.setWidth(6)
        gauge_pen.setCapStyle(Qt.FlatCap)
        p.setPen(gauge_pen)
        p.drawArc(int(cx - rad), int(cy - rad), int(rad * 2), int(rad * 2), 0, 180 * 16)
        frac = self.value / 10.0
        ang = 180 - frac * 180
        import math
        rad_a = math.radians(ang)
        nx = cx + rad * 0.82 * math.cos(rad_a)
        ny = cy - rad * 0.82 * math.sin(rad_a)
        p.setPen(QPen(QColor("#d9534f"), 2))
        p.drawLine(QPointF(cx, cy), QPointF(nx, ny))
        p.setPen(QColor("#333"))
        p.setFont(QFont("Sans Serif", 7))
        for i in range(0, 11, 2):
            a = math.radians(180 - (i / 10.0) * 180)
            tx = cx + (rad + 10) * math.cos(a)
            ty = cy - (rad + 10) * math.sin(a)
            p.drawText(QRectF(tx - 8, ty - 7, 16, 14), Qt.AlignCenter, str(i))
        p.setPen(QColor("#204a87"))
        p.setFont(QFont("Sans Serif", 8, QFont.Bold))
        p.drawText(QRectF(0, 2, w, 14), Qt.AlignCenter, "SITE TARGET")
        p.end()


class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(320)
        mw = main_window
        layout = QVBoxLayout(self)

        grid_box = QGroupBox("Map Table Grid")
        grid_form = QFormLayout(grid_box)
        self.spin_cols = QSpinBox(); self.spin_cols.setRange(4, 400); self.spin_cols.setValue(mw.spin_cols_val)
        self.spin_cols.valueChanged.connect(mw.on_cols_changed)
        grid_form.addRow("Columns", self.spin_cols)
        self.spin_rows = QSpinBox(); self.spin_rows.setRange(4, 400); self.spin_rows.setValue(mw.spin_rows_val)
        self.spin_rows.valueChanged.connect(mw.on_rows_changed)
        grid_form.addRow("Rows", self.spin_rows)
        self.chk_link_aspect = QCheckBox("Lock to video aspect ratio")
        self.chk_link_aspect.setChecked(mw.lock_aspect)
        self.chk_link_aspect.stateChanged.connect(mw.on_lock_aspect_changed)
        grid_form.addRow(self.chk_link_aspect)
        note = QLabel("More rows/columns = finer gradient. Past ~4000 cells,\nper-cell numbers auto-hide for speed.")
        note.setStyleSheet("color:#777; font-size:10px;")
        grid_form.addRow(note)
        layout.addWidget(grid_box)

        view_box = QGroupBox("Table Display")
        view_form = QFormLayout(view_box)
        self.chk_show_values = QCheckBox("Show cell values"); self.chk_show_values.setChecked(True)
        self.chk_show_values.stateChanged.connect(mw.on_show_values_changed)
        view_form.addRow(self.chk_show_values)
        self.chk_show_axis = QCheckBox("Show axis headers"); self.chk_show_axis.setChecked(True)
        self.chk_show_axis.stateChanged.connect(mw.on_show_axis_changed)
        view_form.addRow(self.chk_show_axis)
        layout.addWidget(view_box)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.close)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.close)
        layout.addWidget(btns)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} — File Loaded : (none)")
        self.resize(1440, 900)

        self.cap = None
        self.total_frames = 0
        self.src_fps = 30.0
        self.frame_idx = 0
        self.playing = False
        self.contrast = 1.0
        self.invert = False
        self.speed = 1.0
        self.map_type = "fuel"
        self.lock_aspect = True
        self.spin_cols_val = 28
        self.spin_rows_val = 18
        self.graph_cols = 40
        self.graph_rows = 22
        self.table_lut_name = "Pastel"
        self.prev_luma = None
        self.fps_hist = []
        self.last_tick = time.time()
        self.settings_dialog = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_frame)

        self._build_ui()
        self._apply_style()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # fake closable tab strip
        tabstrip = QHBoxLayout()
        tabstrip.setContentsMargins(4, 3, 4, 0)
        tabstrip.setSpacing(0)
        self.lbl_tab = QLabel("Main Injection Quantity   ✕")
        self.lbl_tab.setObjectName("TabChip")
        tabstrip.addWidget(self.lbl_tab)
        tabstrip.addStretch(1)
        tabstrip_wrap = QWidget(); tabstrip_wrap.setLayout(tabstrip)
        tabstrip_wrap.setObjectName("TabStrip")
        root.addWidget(tabstrip_wrap)

        # main split: (table | 3D graph) over 2D graph
        self.heatmap = HeatmapWidget()

        try:
            self.gl_view = gl.GLViewWidget()
            self.gl_view.setCameraPosition(distance=45, elevation=28, azimuth=-60)
            self.gl_view.setMinimumSize(280, 200)
            gx = gl.GLGridItem(); gx.setSize(40, 40); gx.setSpacing(4, 4)
            gx.translate(0, 0, -0.01)
            self.gl_view.addItem(gx)
            init_z = np.zeros((self.graph_cols, self.graph_rows), dtype=np.float32)
            init_c = np.zeros((self.graph_cols, self.graph_rows, 4), dtype=np.float32)
            init_c[..., 3] = 1.0
            self.surface = gl.GLSurfacePlotItem(
                x=np.linspace(-18, 18, self.graph_cols),
                y=np.linspace(-12, 12, self.graph_rows),
                z=init_z, colors=init_c, shader='shaded', smooth=True)
            self.gl_view.addItem(self.surface)
            self._gl_ok = True
        except Exception:
            self.gl_view = QLabel("3D graph unavailable\n(no OpenGL context on this system)")
            self.gl_view.setAlignment(Qt.AlignCenter)
            self._gl_ok = False

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self.heatmap)
        top_splitter.addWidget(self.gl_view)
        top_splitter.setSizes([650, 550])

        self.plot2d = pg.PlotWidget()
        self.plot2d.setMinimumHeight(160)
        self.plot2d.showGrid(x=True, y=True, alpha=0.25)
        self.plot2d.setLabel('bottom', 'RPM')
        self.plot2d.setLabel('left', 'Value')
        self.curves = []
        for i in range(self.graph_rows):
            col = JET_LUT[int(i / max(1, self.graph_rows - 1) * 255)]
            pen = pg.mkPen(color=(int(col[0]), int(col[1]), int(col[2])), width=1.2)
            self.curves.append(self.plot2d.plot(pen=pen))

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self.plot2d)
        main_splitter.setSizes([560, 200])
        root.addWidget(main_splitter, 1)

        # description box
        self.lbl_desc = QLabel(MAP_TYPES[self.map_type]["desc"])
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setObjectName("DescBox")
        self.lbl_desc.setFixedHeight(46)
        root.addWidget(self.lbl_desc)

        self.setCentralWidget(central)

        self._build_left_tree()
        self._build_right_panel()
        self._build_toolbar_and_menu()
        self._build_statusbar()

    def _build_left_tree(self):
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setIndentation(14)

        def leaf(parent, label, key=None):
            it = QTreeWidgetItem(parent, [label])
            if key:
                it.setData(0, Qt.UserRole, key)
            return it

        engine = QTreeWidgetItem(tree, ["Engine Calibration"])
        leaf(engine, "Acceleration Fuelling")
        leaf(engine, "Alternate Maps")
        leaf(engine, "Anti-Lag System")
        leaf(engine, "Auxiliary Functions")
        base = QTreeWidgetItem(engine, ["Base Mapping"])
        leaf(base, "Main Injection Quantity", "fuel")
        leaf(base, "Main Spark Advance", "spark")
        leaf(base, "AFR Target Map", "afr")
        leaf(engine, "Boost Control", "boost")
        leaf(engine, "Data Logger")
        leaf(engine, "ECU Configuration")
        leaf(engine, "Fuel Correction Factors", "injector")
        leaf(engine, "Gear Shift Control")
        leaf(engine, "Idle Speed Control")
        leaf(engine, "Ignition Correction Factors", "timing")
        leaf(engine, "Inputs & Outputs Test")
        leaf(engine, "Knock Control")
        leaf(engine, "On Board Diagnostics (OBD)")
        leaf(engine, "Overrun Fuel Cut-off")
        leaf(engine, "Rev Limiter")
        leaf(engine, "Sensor Setup")
        leaf(engine, "Variable Cam Timing")
        QTreeWidgetItem(tree, ["Gauges"])
        QTreeWidgetItem(tree, ["Scope"])
        QTreeWidgetItem(tree, ["Config"])
        tree.expandItem(engine)
        tree.expandItem(base)
        tree.itemClicked.connect(self.on_tree_item_clicked)
        self.tree = tree

        dock = QDockWidget("ECU", self)
        dock.setWidget(tree)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        dock.setMinimumWidth(220)

    def _build_right_panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        title = QLabel("LIVE DATA"); title.setObjectName("SectionTitle")
        v.addWidget(title)

        self.live_labels = {}
        fields = [
            ("rpm", "Engine Speed RPM"), ("tps", "Throttle Position %"),
            ("map", "Manifold Press mBar"), ("inj", "Inj ms"),
            ("lambda_t", "Target Lambda"), ("base_pw", "Base Inj PW ms"),
            ("final_pw", "Final Inj 1 PW ms"), ("clt", "Coolant Temp °C"),
            ("iat", "Air Temp °C"), ("lambda_w", "Wideband Lambda 1"),
            ("cl_corr", "Closed Loop Corr 1 %"),
        ]
        for key, label in fields:
            row = QHBoxLayout()
            lab = QLabel(label); lab.setObjectName("LiveLabel")
            val = QLabel("0.0"); val.setObjectName("LiveValue"); val.setAlignment(Qt.AlignRight)
            row.addWidget(lab, 1); row.addWidget(val)
            v.addLayout(row)
            self.live_labels[key] = val

        v.addSpacing(10)
        self.gauge = SiteTargetGauge()
        v.addWidget(self.gauge)
        v.addStretch(1)

        dock = QDockWidget("Live Data", self)
        dock.setWidget(panel)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        dock.setTitleBarWidget(QWidget())
        dock.setMinimumWidth(210)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_toolbar_and_menu(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(pg.QtCore.QSize(16, 16)) if False else None

        def add_icon_btn(kind_or_color, tooltip, callback, is_color=False):
            btn = QToolButton()
            if is_color:
                btn.setIcon(make_swatch_icon(QColor(kind_or_color)))
            else:
                btn.setIcon(make_symbol_icon(kind_or_color))
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            tb.addWidget(btn)
            return btn

        add_icon_btn("save", "Save Calibration", lambda: self.sb_status.setText("SAVE (demo)"))
        add_icon_btn("folder", "Open Calibration / Video…", self.open_video)
        tb.addSeparator()

        # --- transport control ---
        add_icon_btn("#4caf50", "Start Logging", self.play, is_color=True)
        add_icon_btn("#e0a83f", "Pause Logging", self.pause, is_color=True)
        add_icon_btn("#d9534f", "Stop & Reset Logging", self.stop, is_color=True)
        tb.addSeparator()

        add_icon_btn("undo", "Undo", lambda: None)
        add_icon_btn("undo", "Redo", lambda: None)
        tb.addSeparator()

        add_icon_btn("minus", "Decrease value spread", lambda: self._nudge_contrast(-0.1))
        add_icon_btn("plus", "Increase value spread", lambda: self._nudge_contrast(0.1))
        add_icon_btn("star", "Invert polarity", self._toggle_invert)
        add_icon_btn("zero", "Reset value spread", lambda: self._set_contrast(1.0))
        tb.addSeparator()

        add_icon_btn("#7f86e0", "Palette: Pastel", lambda: self._set_palette("Pastel"), is_color=True)
        add_icon_btn("#3fae5a", "Palette: Vivid", lambda: self._set_palette("Vivid"), is_color=True)
        add_icon_btn("#d9534f", "Palette: Thermal", lambda: self._set_palette("Thermal"), is_color=True)
        tb.addSeparator()

        tb.addWidget(QLabel("  X  Y  "))
        zoom_lbl = QLabel(" Zoom ")
        tb.addWidget(zoom_lbl)
        self.slider_zoom = QSlider(Qt.Horizontal)
        self.slider_zoom.setFixedWidth(110)
        self.slider_zoom.setRange(16, 90)
        self.slider_zoom.setValue(self.graph_cols)
        self.slider_zoom.valueChanged.connect(self.on_zoom_changed)
        tb.addWidget(self.slider_zoom)

        self.addToolBar(tb)

        m_file = self.menuBar().addMenu("&File")
        act_open = QAction("Open Video…", self); act_open.triggered.connect(self.open_video)
        m_file.addAction(act_open)
        m_file.addSeparator()
        act_quit = QAction("Exit", self); act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_tools = self.menuBar().addMenu("&Tools")
        act_settings = QAction("Settings…", self); act_settings.triggered.connect(self.open_settings)
        m_tools.addAction(act_settings)

        m_help = self.menuBar().addMenu("&Help")
        act_about = QAction("About", self); act_about.triggered.connect(self.show_about)
        m_help.addAction(act_about)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.sb_help = QLabel("Press F1 for help")
        self.sb_status = QLabel("Idle")
        self.sb_grid = QLabel("—")
        self.sb_online = QLabel("○  Offline")
        sb.addWidget(self.sb_help)
        sb.addWidget(QLabel("   |   "))
        sb.addWidget(self.sb_status)
        sb.addPermanentWidget(self.sb_grid)
        sb.addPermanentWidget(QLabel("    "))
        sb.addPermanentWidget(self.sb_online)
        self.setStatusBar(sb)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #ece9e4; }
            QMenuBar { background: #f4f3f0; color: #202020; border-bottom: 1px solid #b9b9b9; }
            QMenuBar::item:selected { background: #cfe0f5; }
            QMenu { background: #ffffff; color: #202020; border: 1px solid #b9b9b9; }
            QMenu::item:selected { background: #cfe0f5; }
            QToolBar { background: #e8e6e1; border-bottom: 1px solid #b9b9b9; spacing: 3px; padding: 3px; }
            QToolButton { background: #f4f3f0; border: 1px solid #c7c3ba; padding: 3px; border-radius: 2px; }
            QToolButton:hover { background: #dcebfa; border-color: #7fa8d9; }
            QStatusBar { background: #e8e6e1; border-top: 1px solid #b9b9b9; color: #333; font-size: 11px; }
            QDockWidget { background: #f4f3f0; border: 1px solid #c7c3ba; }
            QTreeWidget { background: #ffffff; border: none; font-size: 12px; }
            QTreeWidget::item { padding: 2px; }
            QTreeWidget::item:selected { background: #cfe0f5; color: #000; }
            QWidget#TabStrip { background: #d8d4cb; border-bottom: 1px solid #b9b9b9; }
            QLabel#TabChip { background: #ffffff; border: 1px solid #b9b9b9; border-bottom: none;
                              padding: 5px 14px; border-top-left-radius: 3px; border-top-right-radius: 3px; }
            QLabel#DescBox { background: #fffef2; border-top: 1px solid #b9b9b9; padding: 6px 10px;
                              color: #444; font-size: 11px; }
            QLabel#SectionTitle { font-weight: bold; color: #555; font-size: 10px; letter-spacing: 1px;
                                   border-bottom: 1px solid #d0d0d0; padding-bottom: 4px; margin-bottom: 4px; }
            QLabel#LiveLabel { color: #555; font-size: 11px; }
            QLabel#LiveValue { color: #204a87; font-weight: bold; font-size: 11px; font-family: monospace; }
            QSlider::groove:horizontal { height: 4px; background: #c7c3ba; }
            QSlider::handle:horizontal { background: #3f7fd1; width: 11px; margin: -4px 0; border-radius: 1px; }
            QGroupBox { font-weight: bold; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        """)

    # ---------------- video I/O ----------------
    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open datalog file (video)", "",
            "Video files (*.mp4 *.avi *.mkv *.mov *.webm *.wmv);;All files (*)")
        if not path:
            return
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.warning(self, "Could not open file", "This file could not be read as a video.")
            return
        self.cap = cap
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        self.src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.frame_idx = 0
        self.prev_luma = None
        fname = path.split("/")[-1].split("\\")[-1]
        self.setWindowTitle(f"{APP_TITLE} — File Loaded : {fname}")
        self.sb_status.setText("Connected")
        self.sb_online.setText("●  Online")
        self.sb_online.setStyleSheet("color: #2e8b2e; font-weight: bold;")

        if self.lock_aspect:
            vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 4
            vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 3
            rows = int(round(self.spin_cols_val * (vh / vw)))
            self.spin_rows_val = max(4, min(400, rows))
            if self.settings_dialog is not None:
                self.settings_dialog.spin_rows.blockSignals(True)
                self.settings_dialog.spin_rows.setValue(self.spin_rows_val)
                self.settings_dialog.spin_rows.blockSignals(False)

        self.render_current_frame()

    def play(self):
        if self.cap is None:
            return
        self.playing = True
        interval = max(10, int(1000 / (self.src_fps * self.speed)))
        self.timer.start(interval)

    def pause(self):
        self.playing = False
        self.timer.stop()

    def stop(self):
        self.pause()
        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.frame_idx = 0
            self.render_current_frame()

    def advance_frame(self):
        if not self.render_current_frame():
            self.pause()

    def render_current_frame(self):
        if self.cap is None:
            return False
        ret, frame = self.cap.read()
        if not ret:
            return False
        self.frame_idx += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # -- table grid --
        cols, rows = self.spin_cols_val, self.spin_rows_val
        small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        gamma = 1.0 / max(0.15, self.contrast)
        small = np.power(np.clip(small, 0, 1), gamma)
        if self.invert:
            small = 1.0 - small
        motion = 0.0
        if self.prev_luma is not None and self.prev_luma.shape == small.shape:
            motion = float(np.mean(np.abs(small - self.prev_luma)))
        self.prev_luma = small
        idx = (small * 255).astype(np.uint8)
        lut = TABLE_LUTS[self.table_lut_name]
        rgb = np.ascontiguousarray(lut[idx])
        meta = MAP_TYPES[self.map_type]
        values = meta["min"] + small * (meta["max"] - meta["min"])
        self.heatmap.set_frame(rgb, values, meta["dec"])

        # -- graph grid --
        gcols, grows = self.graph_cols, self.graph_rows
        gsmall = cv2.resize(gray, (gcols, grows), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        self._update_graphs(gsmall)

        avg = float(np.mean(small))
        self._update_gauges(avg, motion)
        self._update_live_data(avg, motion)

        if self.total_frames > 0:
            pass
        self.lbl_tab.setText(f"{meta['title']}   ✕")
        self.sb_grid.setText(f"GRID {cols}x{rows}   FRAME {self.frame_idx:04d}/{self.total_frames:04d}")

        now = time.time()
        dt = now - self.last_tick
        self.last_tick = now
        if dt > 0:
            self.fps_hist.append(1.0 / dt)
            if len(self.fps_hist) > 20:
                self.fps_hist.pop(0)
        return True

    def _update_graphs(self, gsmall):
        grows, gcols = gsmall.shape
        # -- 3D surface --
        if self._gl_ok:
            z = gsmall.T * 9.0  # (gcols, grows) height amplitude
            idx = (gsmall.T * 255).astype(np.uint8)
            rgb = JET_LUT[idx].astype(np.float32) / 255.0
            colors = np.dstack([rgb, np.ones(rgb.shape[:2], dtype=np.float32)])
            try:
                self.surface.setData(z=z, colors=colors)
            except Exception:
                pass
        # -- 2D lines: one curve per row, x = column index (RPM axis) --
        xs = np.array([rpm_for_col(c, gcols) for c in range(gcols)])
        for r in range(min(grows, len(self.curves))):
            self.curves[r].setData(xs, gsmall[r, :] * 100.0)

    def _update_gauges(self, avg_luma, motion):
        self.gauge.set_value(avg_luma * 10.0)

    def _update_live_data(self, avg_luma, motion):
        rpm = int(800 + avg_luma * 7200)
        self.live_labels["rpm"].setText(f"{rpm}")
        self.live_labels["tps"].setText(f"{avg_luma*100:.1f}")
        self.live_labels["map"].setText(f"{300 + avg_luma*700:.0f}")
        inj = 2 + avg_luma * 10
        self.live_labels["inj"].setText(f"{inj:.2f}")
        self.live_labels["lambda_t"].setText(f"{0.85 + avg_luma*0.2:.2f}")
        self.live_labels["base_pw"].setText(f"{inj*0.9:.2f}")
        self.live_labels["final_pw"].setText(f"{inj:.2f}")
        self.live_labels["clt"].setText(f"{88 + motion*20:.1f}")
        self.live_labels["iat"].setText(f"{24 + avg_luma*8:.1f}")
        self.live_labels["lambda_w"].setText(f"{0.9 + avg_luma*0.3:.2f}")
        self.live_labels["cl_corr"].setText(f"{(avg_luma-0.5)*20:.1f}")

    # ---------------- control callbacks ----------------
    def _rerender_if_paused(self):
        if self.cap is not None and not self.playing:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, self.frame_idx - 1))
            self.render_current_frame()

    def _nudge_contrast(self, delta):
        self._set_contrast(self.contrast + delta)

    def _set_contrast(self, v):
        self.contrast = max(0.15, min(3.0, v))
        self._rerender_if_paused()

    def _toggle_invert(self):
        self.invert = not self.invert
        self._rerender_if_paused()

    def _set_palette(self, name):
        self.table_lut_name = name
        self._rerender_if_paused()

    def on_zoom_changed(self, v):
        self.graph_cols = v
        self.graph_rows = max(8, int(v * 0.55))
        # rebuild curves + surface axes for new resolution
        self.plot2d.clear()
        self.curves = []
        for i in range(self.graph_rows):
            col = JET_LUT[int(i / max(1, self.graph_rows - 1) * 255)]
            pen = pg.mkPen(color=(int(col[0]), int(col[1]), int(col[2])), width=1.2)
            self.curves.append(self.plot2d.plot(pen=pen))
        if self._gl_ok:
            self.gl_view.removeItem(self.surface)
            init_z = np.zeros((self.graph_cols, self.graph_rows), dtype=np.float32)
            init_c = np.zeros((self.graph_cols, self.graph_rows, 4), dtype=np.float32)
            init_c[..., 3] = 1.0
            self.surface = gl.GLSurfacePlotItem(
                x=np.linspace(-18, 18, self.graph_cols),
                y=np.linspace(-12, 12, self.graph_rows),
                z=init_z, colors=init_c, shader='shaded', smooth=True)
            self.gl_view.addItem(self.surface)
        self._rerender_if_paused()

    def on_tree_item_clicked(self, item, col):
        key = item.data(0, Qt.UserRole)
        if not key:
            self.sb_status.setText(f"'{item.text(0)}' — not available in this preview")
            return
        self.map_type = key
        meta = MAP_TYPES[key]
        self.lbl_tab.setText(f"{meta['title']}   ✕")
        self.lbl_desc.setText(meta["desc"])
        self._rerender_if_paused()

    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def on_cols_changed(self, v):
        self.spin_cols_val = v
        self._rerender_if_paused()

    def on_rows_changed(self, v):
        self.spin_rows_val = v
        self._rerender_if_paused()

    def on_lock_aspect_changed(self, state):
        self.lock_aspect = bool(state)

    def on_show_values_changed(self, state):
        self.heatmap.show_values = bool(state)
        self.heatmap.update()

    def on_show_axis_changed(self, state):
        self.heatmap.show_axis = bool(state)
        self.heatmap.update()

    def show_about(self):
        QMessageBox.information(
            self, "About ECU MAPPER RT",
            "ECU MAPPER RT\n\nRenders any local video as a live, adjustable "
            "heatmap tuning table with real-time 2D/3D graphs, styled after "
            "classic ECU calibration software.\n\nLoad your own file via the "
            "folder icon in the toolbar.")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#ece9e4"))
    pal.setColor(QPalette.WindowText, QColor("#202020"))
    pal.setColor(QPalette.Base, QColor("#ffffff"))
    pal.setColor(QPalette.Text, QColor("#202020"))
    pal.setColor(QPalette.Button, QColor("#f4f3f0"))
    pal.setColor(QPalette.ButtonText, QColor("#202020"))
    app.setPalette(pal)
    app.setApplicationName(APP_TITLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
