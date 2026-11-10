"""The single Vox window."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from . import APP_NAME, __version__, profiles
from .devices import (
    AudioDevice,
    DeviceSet,
    pick_input,
    pick_monitor,
    pick_output,
    scan,
)
from .engine import AudioEngine, EngineStats, IsolationModel, gpu_available
from .paths import assets_dir, logs_dir
from .profiles import ProfileError, RecordingCancelled
from .settings import Settings, load_settings, save_settings
from .theme import (
    ACCENT,
    BLUE,
    DIM,
    ERROR,
    MUTED,
    TEXT,
    WARN,
    app_icon,
    enable_dark_title_bar,
)

log = logging.getLogger(__name__)

GITHUB_URL = "https://github.com/DetectiveLon/Vox"
CABLE_URL = "https://vb-audio.com/Cable/"


class LevelMeter(QWidget):
    """A small, smoothed RMS meter. Speech looks dead on a linear scale, so the
    level is square-rooted before drawing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target = 0.0
        self._level = 0.0
        self.setFixedHeight(8)
        self.setMinimumWidth(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._decay)
        self._timer.start(33)

    def set_level(self, rms: float) -> None:
        value = max(0.0, min(1.0, float(rms)))
        self._target = value**0.5

    def _decay(self) -> None:
        if self._target >= self._level:
            self._level = self._target
        else:
            self._level *= 0.86
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#10141b"))
        painter.drawRoundedRect(rect, 4, 4)
        if self._level > 0.004:
            width = max(2, int(rect.width() * self._level))
            fill = rect.adjusted(0, 0, -(rect.width() - width), 0)
            gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
            gradient.setColorAt(0.0, QColor(ACCENT))
            gradient.setColorAt(0.62, QColor(ACCENT))
            gradient.setColorAt(0.84, QColor(WARN))
            gradient.setColorAt(1.0, QColor(ERROR))
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 4, 4)


class Waveform(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks: list[float] = []
        self.setFixedHeight(54)

    def set_peaks(self, peaks: list[float]) -> None:
        self._peaks = list(peaks)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#10141b"))
        painter.drawRoundedRect(rect, 8, 8)
        middle = rect.center().y()
        if not self._peaks:
            painter.setPen(QPen(QColor("#283040"), 1))
            painter.drawLine(rect.left() + 12, middle, rect.right() - 12, middle)
            return
        count = len(self._peaks)
        width = rect.width() - 20
        max_height = rect.height() * 0.42
        pen = QPen(QColor(45, 212, 167, 200))
        pen.setWidthF(max(1.0, width / count * 0.48))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        for index, peak in enumerate(self._peaks):
            x = rect.left() + 10 + (index + 0.5) * width / count
            height = max(0.8, float(peak) * max_height)
            painter.drawLine(QPointF(x, middle - height), QPointF(x, middle + height))


class StatusPill(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Pill")
        self.setTextFormat(Qt.RichText)
        self.setAlignment(Qt.AlignCenter)
        self._state = ""
        self.set_state("Setup needed", "warn")

    def set_state(self, text: str, tone: str = "idle") -> None:
        key = f"{text}|{tone}"
        if key == self._state:
            return
        self._state = key
        colors = {
            "idle": DIM,
            "ok": ACCENT,
            "warn": WARN,
            "error": ERROR,
            "busy": BLUE,
        }
        self.setText(f'<span style="color:{colors.get(tone, DIM)}">●</span>&nbsp;&nbsp;{text}')


class Card(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 15, 18, 16)
        outer.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        label = QLabel(title.upper())
        label.setObjectName("CardTitle")
        self.header.addWidget(label)
        self.header.addStretch(1)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)


def field_label(text: str, width: int = 86) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    label.setFixedWidth(width)
    return label


def inline_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


class RecordThread(QThread):
    level = Signal(float)
    progress = Signal(float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, device: AudioDevice, seconds: float, parent=None) -> None:
        super().__init__(parent)
        self.device = device
        self.seconds = seconds
        self._stop = threading.Event()
        self._last_emit = 0.0

    def cancel(self) -> None:
        self._stop.set()

    def _progress(self, fraction: float, level: float) -> None:
        now = time.monotonic()
        if now - self._last_emit >= 0.07:
            self._last_emit = now
            self.level.emit(level)
            self.progress.emit(fraction)

    def run(self) -> None:
        try:
            audio = profiles.record(
                self.device, self.seconds, self._stop, self._progress
            )
            self.done.emit(audio)
        except RecordingCancelled:
            return
        except Exception as exc:
            log.exception("Recording failed")
            self.failed.emit(str(exc))


class RecordDialog(QDialog):
    def __init__(self, device: AudioDevice, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self.saved_path: Path | None = None
        self._thread: RecordThread | None = None
        self.setWindowTitle("Record a voice sample")
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setWindowIcon(app_icon())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Record your voice")
        title.setStyleSheet("font-size: 16pt; font-weight: 700;")
        layout.addWidget(title)
        description = QLabel(
            "Use the microphone you will actually use. Read something in your normal "
            "voice for 10 seconds, with nobody else talking."
        )
        description.setObjectName("Muted")
        description.setWordWrap(True)
        layout.addWidget(description)

        row = QHBoxLayout()
        row.setSpacing(10)
        name_label = inline_label("Profile name")
        self.name_edit = QLineEdit("My voice")
        self.name_edit.setPlaceholderText("My voice")
        row.addWidget(name_label)
        row.addWidget(self.name_edit, 1)
        layout.addLayout(row)

        self.meter = LevelMeter()
        layout.addWidget(self.meter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status = QLabel(f"Ready. Recording takes {profiles.DEFAULT_SECONDS:.0f} seconds.")
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.start_btn = QPushButton("Start recording")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.clicked.connect(self._stop_recording)
        self.stop_btn.setVisible(False)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.start_btn)
        layout.addLayout(buttons)

    def _start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self.progress.setValue(0)
        self.meter.set_level(0)
        self.status.setText("Recording... speak normally.")
        self.status.setObjectName("Good")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.name_edit.setEnabled(False)
        self.start_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.cancel_btn.setEnabled(False)
        self._thread = RecordThread(self.device, profiles.DEFAULT_SECONDS, self)
        self._thread.level.connect(self.meter.set_level)
        self._thread.progress.connect(lambda value: self.progress.setValue(int(value * 100)))
        self._thread.done.connect(self._finished)
        self._thread.failed.connect(self._failed)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _stop_recording(self) -> None:
        self.status.setText("Stopping...")
        self.stop_btn.setEnabled(False)
        if self._thread is not None:
            self._thread.cancel()

    def _thread_finished(self) -> None:
        self.stop_btn.setVisible(False)
        self.start_btn.setVisible(True)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Record again")
        self.name_edit.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        if not self.isVisible():
            return

    def _finished(self, audio: object) -> None:
        name = self.name_edit.text().strip() or "My voice"
        try:
            self.saved_path = profiles.save_profile(name, np.asarray(audio))
        except ProfileError as exc:
            self._failed(str(exc))
            return
        self.progress.setValue(100)
        self.status.setText("Saved. This profile is ready to use.")
        self.status.setObjectName("Good")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        QTimer.singleShot(350, self.accept)

    def _failed(self, message: str) -> None:
        self.status.setText("Recording failed.")
        self.status.setObjectName("Warn")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        QMessageBox.warning(self, "Could not record", message)

    def reject(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(2000)
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(2000)
        super().closeEvent(event)


class StartWorker(QThread):
    ok = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        model: IsolationModel,
        sample: np.ndarray,
        input_device: AudioDevice,
        output_device: AudioDevice,
        monitor_device: AudioDevice | None,
        gain_db: float,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.sample = sample
        self.input_device = input_device
        self.output_device = output_device
        self.monitor_device = monitor_device
        self.gain_db = gain_db
        self.result: AudioEngine | None = None
        self.error = ""

    def run(self) -> None:
        try:
            self.model.load()
            engine = AudioEngine(
                self.model,
                self.sample,
                self.input_device,
                self.output_device,
                self.monitor_device,
                self.gain_db,
            )
            engine.start()
            self.result = engine
            self.ok.emit(engine)
        except Exception as exc:
            self.error = str(exc)
            log.exception("Could not start the engine")
            self.failed.emit(self.error)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(480)
        self.setWindowIcon(app_icon())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        title = QLabel(f"{APP_NAME} {__version__}")
        title.setStyleSheet("font-size: 17pt; font-weight: 800;")
        layout.addWidget(title)
        subtitle = QLabel("Keep your voice. Drop the rest.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setFrameShape(QFrame.NoFrame)
        text.setMinimumHeight(190)
        text.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        text.setHtml(
            f"""
            <p style="color:{TEXT}">Vox isolates the voice in your profile and removes
            competing voices before they reach Discord, OBS, Zoom or a game.</p>
            <p style="color:{MUTED}">All audio is processed on this PC. Vox does not
            record, store or upload it.</p>
            <p style="color:{MUTED}">Voice isolation by
            <a href="https://github.com/arbazsiddiqui/voxlock" style="color:{ACCENT}">VoxLock</a>
            (Apache-2.0), running on ONNX Runtime. Interface built with PySide6.
            Virtual microphone by VB-CABLE (donationware, installed separately).</p>
            <p style="color:{DIM}">Vox is open source:
            <a href="{GITHUB_URL}" style="color:{ACCENT}">{GITHUB_URL}</a></p>
            """
        )
        layout.addWidget(text)

        buttons = QHBoxLayout()
        logs = QPushButton("Open log folder")
        logs.setObjectName("Ghost")
        logs.clicked.connect(self._open_logs)
        github = QPushButton("GitHub")
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(logs)
        buttons.addStretch(1)
        buttons.addWidget(github)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _open_logs(self) -> None:
        logs_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(str(logs_dir()))  # type: ignore[attr-defined]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.device_set: DeviceSet = scan()
        self.profile_infos: list[profiles.ProfileInfo] = profiles.list_profiles()
        self._sample: np.ndarray | None = None
        self._profile_error = ""
        self._engine: AudioEngine | None = None
        self._model: IsolationModel | None = None
        self._start_worker: StartWorker | None = None
        self._closing = False
        self._error_shown = ""
        self._session_overruns = 0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(720, 620)
        self.resize(self.settings.window_w, self.settings.window_h)

        self._build()
        self._populate_device_combos()
        self._apply_processing_settings()
        self._refresh_profiles(self.settings.profile)
        self._update_cable_status()
        self._update_audio_hint()
        self._update_mode_hint()
        self._update_latency_hint()
        self._fit_size()
        self._update_state()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)
        QTimer.singleShot(0, lambda: enable_dark_title_bar(self))

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        content = QWidget()
        content.setObjectName("Content")
        self._content = content
        outer = QVBoxLayout(content)
        outer.setContentsMargins(22, 18, 22, 14)
        outer.setSpacing(13)

        header = QHBoxLayout()
        header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        logo = QLabel('VO<span style="color:#2dd4a7">X</span>')
        logo.setObjectName("Logo")
        logo.setTextFormat(Qt.RichText)
        tagline = QLabel("Keep your voice. Drop the rest.")
        tagline.setObjectName("Tagline")
        titles.addWidget(logo)
        titles.addWidget(tagline)
        header.addLayout(titles)
        header.addStretch(1)
        self.status_pill = StatusPill()
        header.addWidget(self.status_pill, 0, Qt.AlignTop)
        outer.addLayout(header)

        self.banner = self._build_banner()
        outer.addWidget(self.banner)
        self.banner.setVisible(False)

        outer.addWidget(self._build_voice_card())
        outer.addWidget(self._build_audio_card())
        outer.addWidget(self._build_processing_card())
        outer.addStretch(1)

        action = QHBoxLayout()
        action.setSpacing(10)
        self.status_detail = QLabel("Ready")
        self.status_detail.setObjectName("Muted")
        action.addWidget(self.status_detail, 1)
        self.bypass_btn = QPushButton("Bypass")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setObjectName("Bypass")
        self.bypass_btn.setToolTip(
            "Send the raw microphone through instead of the isolated voice."
        )
        self.bypass_btn.clicked.connect(self._on_bypass)
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumWidth(140)
        self.start_btn.clicked.connect(self._toggle_engine)
        action.addWidget(self.bypass_btn)
        action.addWidget(self.start_btn)
        outer.addLayout(action)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.cable_status = QLabel("Checking VB-CABLE...")
        self.cable_status.setObjectName("Muted")
        self.cable_status.setTextFormat(Qt.RichText)
        footer.addWidget(self.cable_status)
        footer.addStretch(1)
        about = QPushButton("About")
        about.setObjectName("Ghost")
        about.clicked.connect(lambda: AboutDialog(self).exec())
        footer.addWidget(about)
        version = QLabel(f"v{__version__}")
        version.setObjectName("Muted")
        footer.addWidget(version)
        outer.addLayout(footer)

        scroll = QScrollArea()
        scroll.setObjectName("Scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("Banner")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)
        label = QLabel(
            "VB-CABLE is not installed. Discord, OBS and games cannot see Vox "
            "until the virtual microphone exists."
        )
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = QPushButton("Get VB-CABLE")
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CABLE_URL)))
        layout.addWidget(button)
        return banner

    def _build_voice_card(self) -> Card:
        card = Card("Voice profile")
        self.profile_info = QLabel("No voice profile yet")
        self.profile_info.setObjectName("Muted")
        card.add_header_widget(self.profile_info)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.record_btn = QPushButton("Record 10s")
        self.record_btn.clicked.connect(self._on_record)
        self.import_btn = QPushButton("Import WAV")
        self.import_btn.clicked.connect(self._on_import)
        row.addWidget(self.profile_combo, 1)
        row.addWidget(self.record_btn)
        row.addWidget(self.import_btn)
        card.body.addLayout(row)

        self.waveform = Waveform()
        card.body.addWidget(self.waveform)
        self.profile_hint = QLabel(
            "Ten seconds of your normal voice, alone and close to the microphone."
        )
        self.profile_hint.setObjectName("Hint")
        self.profile_hint.setWordWrap(True)
        card.body.addWidget(self.profile_hint)
        return card

    def _build_audio_card(self) -> Card:
        card = Card("Audio")
        refresh = QPushButton("Refresh")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self._on_refresh_devices)
        card.add_header_widget(refresh)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 86)

        self.input_combo = QComboBox()
        self.input_combo.currentIndexChanged.connect(self._on_input_changed)
        self.input_meter = LevelMeter()
        self.input_meter.setToolTip("Input level")
        grid.addWidget(field_label("Microphone"), 0, 0)
        grid.addWidget(self.input_combo, 0, 1)
        grid.addWidget(self.input_meter, 0, 2)

        self.output_combo = QComboBox()
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)
        self.output_meter = LevelMeter()
        self.output_meter.setToolTip("Isolated output level")
        grid.addWidget(field_label("Virtual mic"), 1, 0)
        grid.addWidget(self.output_combo, 1, 1)
        grid.addWidget(self.output_meter, 1, 2)

        self.monitor_combo = QComboBox()
        self.monitor_check = QCheckBox("Enable")
        self.monitor_check.toggled.connect(self._on_monitor_toggled)
        monitor_box = QHBoxLayout()
        monitor_box.setContentsMargins(0, 0, 0, 0)
        monitor_box.addWidget(self.monitor_check)
        monitor_box.addStretch(1)
        grid.addWidget(field_label("Monitor"), 2, 0)
        grid.addWidget(self.monitor_combo, 2, 1)
        grid.addLayout(monitor_box, 2, 2)

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(-12, 12)
        self.gain_slider.setValue(0)
        self.gain_slider.setSingleStep(1)
        self.gain_slider.valueChanged.connect(self._on_gain)
        self.gain_label = QLabel("0 dB")
        self.gain_label.setObjectName("Muted")
        self.gain_label.setFixedWidth(52)
        self.gain_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(field_label("Output level"), 3, 0)
        grid.addWidget(self.gain_slider, 3, 1)
        grid.addWidget(self.gain_label, 3, 2)
        card.body.addLayout(grid)

        self.audio_hint = QLabel("")
        self.audio_hint.setObjectName("Hint")
        self.audio_hint.setWordWrap(True)
        card.body.addWidget(self.audio_hint)
        return card

    def _build_processing_card(self) -> Card:
        card = Card("Processing")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(field_label("Mode"))

        segmented = QFrame()
        segmented.setObjectName("Seg")
        segmented_layout = QHBoxLayout(segmented)
        segmented_layout.setContentsMargins(3, 3, 3, 3)
        segmented_layout.setSpacing(2)
        self.cpu_btn = QPushButton("CPU")
        self.cpu_btn.setObjectName("SegBtn")
        self.cpu_btn.setCheckable(True)
        self.gpu_btn = QPushButton("GPU")
        self.gpu_btn.setObjectName("SegBtn")
        self.gpu_btn.setCheckable(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.cpu_btn)
        self.mode_group.addButton(self.gpu_btn)
        self.mode_group.buttonClicked.connect(self._on_mode_changed)
        segmented_layout.addWidget(self.cpu_btn)
        segmented_layout.addWidget(self.gpu_btn)
        row.addWidget(segmented)
        row.addSpacing(16)

        row.addWidget(inline_label("Chunk"))
        self.chunk_combo = QComboBox()
        self.chunk_combo.addItem("80 ms  ·  stable", 80)
        self.chunk_combo.addItem("40 ms  ·  lower latency", 40)
        self.chunk_combo.currentIndexChanged.connect(self._on_chunk_changed)
        row.addWidget(self.chunk_combo)
        row.addSpacing(16)

        self.threads_label = inline_label("Threads")
        row.addWidget(self.threads_label)
        self.threads_combo = QComboBox()
        for value in (1, 2, 4):
            self.threads_combo.addItem(str(value), value)
        row.addWidget(self.threads_combo)
        row.addStretch(1)
        card.body.addLayout(row)

        info = QHBoxLayout()
        info.setSpacing(12)
        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("Hint")
        self.mode_hint.setWordWrap(True)
        info.addWidget(self.mode_hint, 1)
        self.latency_label = QLabel("")
        self.latency_label.setObjectName("Muted")
        info.addWidget(self.latency_label, 0, Qt.AlignRight | Qt.AlignVCenter)
        card.body.addLayout(info)
        return card

    def _fit_size(self) -> None:
        """Open large enough for the whole window; smaller screens scroll."""
        hint = self._content.sizeHint()
        width = max(self.settings.window_w, hint.width())
        height = max(self.settings.window_h, hint.height())
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            width = min(width, max(720, area.width() - 60))
            height = min(height, max(620, area.height() - 80))
        self.resize(width, height)

    # ------------------------------------------------------------- settings
    def _populate_device_combos(self) -> None:
        previous_input = self.input_combo.currentData() or self.settings.input_device
        previous_output = self.output_combo.currentData() or self.settings.output_device
        previous_monitor = self.monitor_combo.currentData() or self.settings.monitor_device

        self.input_combo.blockSignals(True)
        self.output_combo.blockSignals(True)
        self.monitor_combo.blockSignals(True)
        self.input_combo.clear()
        self.output_combo.clear()
        self.monitor_combo.clear()

        for device in self.device_set.inputs:
            self.input_combo.addItem(device.label, device.key)
        for device in self.device_set.outputs:
            self.output_combo.addItem(device.label, device.key)
        for device in self.device_set.outputs:
            if not device.is_cable_input:
                self.monitor_combo.addItem(device.name, device.key)

        input_device = pick_input(self.device_set, str(previous_input or ""))
        output_device = pick_output(self.device_set, str(previous_output or ""))
        monitor_device = pick_monitor(
            self.device_set, str(previous_monitor or ""), output_device
        )
        if input_device is not None:
            index = self.input_combo.findData(input_device.key)
            self.input_combo.setCurrentIndex(max(0, index))
        if output_device is not None:
            index = self.output_combo.findData(output_device.key)
            self.output_combo.setCurrentIndex(max(0, index))
        if monitor_device is not None:
            index = self.monitor_combo.findData(monitor_device.key)
            self.monitor_combo.setCurrentIndex(max(0, index))

        self.input_combo.blockSignals(False)
        self.output_combo.blockSignals(False)
        self.monitor_combo.blockSignals(False)

        self.input_combo.setEnabled(bool(self.device_set.inputs))
        self.output_combo.setEnabled(bool(self.device_set.outputs))
        self.monitor_combo.setEnabled(bool(self.monitor_combo.count()))
        self.input_meter.setVisible(True)
        self.output_meter.setVisible(True)

    def _apply_processing_settings(self) -> None:
        self.gpu_btn.setEnabled(gpu_available())
        if not self.gpu_btn.isEnabled():
            self.gpu_btn.setToolTip("DirectML is not available in this build.")
            self.settings.mode = "cpu"
        if self.settings.mode == "gpu" and self.gpu_btn.isEnabled():
            self.gpu_btn.setChecked(True)
        else:
            self.cpu_btn.setChecked(True)

        index = self.chunk_combo.findData(self.settings.chunk_ms)
        self.chunk_combo.setCurrentIndex(max(0, index))
        index = self.threads_combo.findData(self.settings.threads)
        self.threads_combo.setCurrentIndex(max(0, index))
        self.gain_slider.setValue(int(round(self.settings.gain_db)))
        self.monitor_check.setChecked(self.settings.monitor_enabled and bool(self.monitor_combo.count()))
        self._on_monitor_toggled(self.monitor_check.isChecked())

    def _sync_settings_from_ui(self) -> None:
        self.settings.input_device = str(self.input_combo.currentData() or "")
        self.settings.output_device = str(self.output_combo.currentData() or "")
        self.settings.monitor_device = str(self.monitor_combo.currentData() or "")
        self.settings.monitor_enabled = self.monitor_check.isChecked()
        self.settings.profile = str(self._selected_profile_path() or "")
        self.settings.mode = "gpu" if self.gpu_btn.isChecked() else "cpu"
        self.settings.chunk_ms = int(self.chunk_combo.currentData() or 80)
        self.settings.threads = int(self.threads_combo.currentData() or 2)
        self.settings.gain_db = float(self.gain_slider.value())
        self.settings.window_w = self.width()
        self.settings.window_h = self.height()

    # -------------------------------------------------------------- profiles
    def _refresh_profiles(self, select: str | Path | None = None) -> None:
        wanted = str(select or "")
        self.profile_infos = profiles.list_profiles()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        if not self.profile_infos:
            self.profile_combo.addItem("No voice profile yet", "")
        else:
            for info in self.profile_infos:
                self.profile_combo.addItem(
                    f"{info.name}   ·   {info.duration:.1f}s", str(info.path)
                )
            if wanted:
                index = self.profile_combo.findData(wanted)
                if index >= 0:
                    self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed()

    def _selected_profile_path(self) -> Path | None:
        data = self.profile_combo.currentData()
        if not data:
            return None
        path = Path(str(data))
        return path if path.is_file() else None

    def _on_profile_changed(self, *args) -> None:
        path = self._selected_profile_path()
        self._sample = None
        self._profile_error = ""
        if path is None:
            self.profile_info.setText("No voice profile yet")
            self.waveform.set_peaks([])
            self.profile_hint.setObjectName("Hint")
            self.profile_hint.setText(
                "Ten seconds of your normal voice, alone and close to the microphone."
            )
            self._restyle(self.profile_hint)
            self._update_state()
            return
        try:
            sample = profiles.load_profile(path)
            self._sample = sample
            self.profile_info.setText(f"{len(sample) / 16000:.1f} s · 16 kHz mono")
            self.waveform.set_peaks(profiles.waveform_peaks(sample, 260))
            self.profile_hint.setObjectName("Hint")
            self.profile_hint.setText(
                "The model keeps this voice and removes other voices from the microphone."
            )
        except Exception as exc:
            self._profile_error = str(exc)
            self.profile_info.setText("Cannot use this profile")
            self.waveform.set_peaks([])
            self.profile_hint.setObjectName("Warn")
            self.profile_hint.setText(str(exc))
            log.warning("Profile %s cannot be used: %s", path, exc)
        self._restyle(self.profile_hint)
        self._update_state()

    def _on_record(self) -> None:
        if self._engine is not None:
            return
        device = self._selected_input()
        if device is None:
            QMessageBox.warning(self, "No microphone", "Select a microphone first.")
            return
        dialog = RecordDialog(device, self)
        if dialog.exec() == QDialog.Accepted and dialog.saved_path is not None:
            self._refresh_profiles(dialog.saved_path)
            self.settings.profile = str(dialog.saved_path)

    def _on_import(self) -> None:
        if self._engine is not None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import a voice sample",
            str(Path.home()),
            "Audio files (*.wav *.flac *.ogg *.aiff);;All files (*)",
        )
        if not path:
            return
        try:
            saved = profiles.import_audio(Path(path))
        except ProfileError as exc:
            QMessageBox.warning(self, "Could not import", str(exc))
            return
        except Exception as exc:
            log.exception("Import failed")
            QMessageBox.warning(self, "Could not import", str(exc))
            return
        self._refresh_profiles(saved)
        self.settings.profile = str(saved)

    # ---------------------------------------------------------------- devices
    def _selected_input(self) -> AudioDevice | None:
        key = str(self.input_combo.currentData() or "")
        return next((device for device in self.device_set.inputs if device.key == key), None)

    def _selected_output(self) -> AudioDevice | None:
        key = str(self.output_combo.currentData() or "")
        return next((device for device in self.device_set.outputs if device.key == key), None)

    def _selected_monitor(self) -> AudioDevice | None:
        if not self.monitor_check.isChecked():
            return None
        key = str(self.monitor_combo.currentData() or "")
        return next(
            (
                device
                for device in self.device_set.outputs
                if device.key == key and not device.is_cable_input
            ),
            None,
        )

    def _on_refresh_devices(self) -> None:
        self.device_set = scan()
        self._populate_device_combos()
        self._update_cable_status()
        self._update_audio_hint()
        self._update_state()

    def _on_input_changed(self, *args) -> None:
        self._update_audio_hint()

    def _on_output_changed(self, *args) -> None:
        self._update_audio_hint()

    def _update_audio_hint(self) -> None:
        microphone = self._selected_input()
        output = self._selected_output()
        if microphone is not None and microphone.is_cable_output:
            self.audio_hint.setObjectName("Warn")
            self.audio_hint.setText(
                "This input is the cable itself, not a microphone. Pick your real "
                "microphone, unless you are routing another app through Vox."
            )
        elif output is not None and not output.is_cable_input:
            self.audio_hint.setObjectName("Warn")
            self.audio_hint.setText(
                "The output is not VB-CABLE, so other apps will not see the cleaned "
                "voice. Use this only to listen to the result."
            )
        elif output is not None:
            self.audio_hint.setObjectName("Hint")
            self.audio_hint.setText(
                "In Discord, OBS or a game, choose CABLE Output as the microphone. "
                "Vox sends the cleaned voice to CABLE Input."
            )
        else:
            self.audio_hint.setObjectName("Warn")
            self.audio_hint.setText("No audio output found. Install VB-CABLE.")
        self._restyle(self.audio_hint)

    def _on_monitor_toggled(self, enabled: bool) -> None:
        self.monitor_combo.setEnabled(
            enabled and self.monitor_combo.count() > 0 and self._engine is None
        )

    def _on_gain(self, value: int) -> None:
        self.gain_label.setText(f"{value:+d} dB" if value else "0 dB")
        if self._engine is not None:
            self._engine.set_gain(float(value))

    # --------------------------------------------------------------- processing
    def _on_mode_changed(self, *args) -> None:
        self._update_mode_hint()
        self._update_latency_hint()
        self._update_state()

    def _on_chunk_changed(self, *args) -> None:
        self._update_latency_hint()

    def _update_mode_hint(self) -> None:
        if self.cpu_btn.isChecked():
            self.mode_hint.setText(
                "Runs on the processor. Works on any PC and needs no graphics card."
            )
            self.mode_hint.setObjectName("Hint")
        else:
            self.mode_hint.setText(
                "Runs on the graphics card through DirectML. Lower CPU load and more "
                "headroom for lowest-latency chunks."
            )
            self.mode_hint.setObjectName("Hint")
        self._restyle(self.mode_hint)
        self.threads_label.setVisible(self.cpu_btn.isChecked())
        self.threads_combo.setVisible(self.cpu_btn.isChecked())

    def _update_latency_hint(self) -> None:
        chunk = int(self.chunk_combo.currentData() or 80)
        estimate = 24 + chunk + 55 + (18 if chunk == 80 else 14)
        if self._engine is not None:
            stats = self._engine.snapshot()
            if stats.rtf > 0:
                estimate = 24 + chunk + stats.infer_ms + 45
        self.latency_label.setText(f"≈ {estimate:.0f} ms end to end")

    def _update_cable_status(self) -> None:
        has_input = self.device_set.cable_input is not None
        has_output = self.device_set.cable_output is not None
        if has_input and has_output:
            self.banner.setVisible(False)
            self.cable_status.setText(
                f'<span style="color:{ACCENT}">●</span>&nbsp;&nbsp;VB-CABLE ready'
            )
        else:
            self.banner.setVisible(True)
            self.cable_status.setText(
                f'<span style="color:{WARN}">●</span>&nbsp;&nbsp;VB-CABLE not found'
            )

    # ------------------------------------------------------------------ state
    def _update_state(self) -> None:
        running = self._engine is not None and self._engine.running
        starting = self._start_worker is not None and self._start_worker.isRunning()
        has_profile = self._sample is not None and not self._profile_error
        devices_ok = self._selected_input() is not None and self._selected_output() is not None
        can_start = has_profile and devices_ok

        self.start_btn.setEnabled((running or can_start) and not starting)
        self.start_btn.setText(
            "Stop" if running else ("Starting..." if starting else "Start")
        )
        self.bypass_btn.setEnabled(running)
        if not running:
            self.bypass_btn.setChecked(False)

        self.record_btn.setEnabled(not running and not starting)
        self.import_btn.setEnabled(not running and not starting)
        self.profile_combo.setEnabled(not running and not starting)
        for widget in (
            self.input_combo,
            self.output_combo,
            self.monitor_check,
            self.cpu_btn,
            self.chunk_combo,
            self.threads_combo,
        ):
            widget.setEnabled(not running and not starting)
        if not running and not starting:
            self.gpu_btn.setEnabled(gpu_available())
            self.monitor_combo.setEnabled(
                self.monitor_check.isChecked() and self.monitor_combo.count() > 0
            )
            self.threads_combo.setEnabled(self.cpu_btn.isChecked())
        else:
            self.gpu_btn.setEnabled(False)
            self.monitor_combo.setEnabled(False)
            self.threads_combo.setEnabled(False)

        self.gain_slider.setEnabled(not starting)
        if starting:
            self.status_pill.set_state("Starting", "busy")
            self.status_detail.setText("Loading the voice model and opening audio devices...")
        elif running:
            if self.bypass_btn.isChecked():
                self.status_pill.set_state("Bypassed", "warn")
                self.status_detail.setText("Bypassed · the raw microphone is being sent")
            else:
                self.status_pill.set_state("Live", "ok")
        elif not has_profile:
            self.status_pill.set_state("Setup needed", "warn")
            self.status_detail.setText("Record or import a voice profile to begin.")
        elif not devices_ok:
            self.status_pill.set_state("Setup needed", "warn")
            self.status_detail.setText("Select a microphone and an output device.")
        else:
            self.status_pill.set_state("Ready", "ok")
            self.status_detail.setText("Ready when you are.")

    def _toggle_engine(self) -> None:
        if self._engine is not None:
            self._stop_engine()
            return
        if self._start_worker is not None and self._start_worker.isRunning():
            return
        if self._closing:
            return
        if self._sample is None or self._profile_error:
            QMessageBox.warning(
                self, "No voice profile", "Record or import a voice profile first."
            )
            return
        microphone = self._selected_input()
        output = self._selected_output()
        monitor = self._selected_monitor()
        if microphone is None or output is None:
            QMessageBox.warning(self, "Audio device missing", "Select an input and an output.")
            return
        if monitor is not None and monitor.index == output.index:
            QMessageBox.warning(
                self,
                "Same monitor device",
                "The monitor and the virtual microphone cannot be the same device.",
            )
            return

        mode = "gpu" if self.gpu_btn.isChecked() else "cpu"
        chunk = int(self.chunk_combo.currentData() or 80)
        threads = int(self.threads_combo.currentData() or 2)
        if self._model is None or self._model.key != (mode, chunk, threads):
            if self._model is not None:
                self._model.unload()
            self._model = IsolationModel(mode=mode, chunk_ms=chunk, threads=threads)

        self.start_btn.setEnabled(False)
        self.start_btn.setText("Starting...")
        self.status_pill.set_state("Starting", "busy")
        self.status_detail.setText("Loading the voice model and opening audio devices...")
        self._error_shown = ""

        worker = StartWorker(
            self._model,
            self._sample,
            microphone,
            output,
            monitor,
            float(self.gain_slider.value()),
            self,
        )
        worker.ok.connect(self._on_start_ok)
        worker.failed.connect(self._on_start_failed)
        worker.finished.connect(self._on_start_finished)
        self._start_worker = worker
        worker.start()

    def _on_start_ok(self, engine: object) -> None:
        if not isinstance(engine, AudioEngine):
            return
        if self._closing:
            engine.stop()
            return
        self._engine = engine
        self._session_overruns = 0
        self.status_detail.setText("Live · waiting for the first block")
        self._update_state()

    def _on_start_failed(self, message: str) -> None:
        self.status_detail.setText("Could not start.")
        self.status_pill.set_state("Error", "error")
        self._update_state()
        QMessageBox.critical(
            self,
            "Could not start",
            f"{message}\n\nDetails are in the log file:\n{logs_dir() / 'vox.log'}",
        )

    def _on_start_finished(self) -> None:
        worker = self.sender()
        if worker is self._start_worker:
            self._start_worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_state()

    def _stop_engine(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            engine.stop()
        self.bypass_btn.setChecked(False)
        self.input_meter.set_level(0.0)
        self.output_meter.set_level(0.0)
        self._update_state()
        self._update_latency_hint()

    def _on_bypass(self) -> None:
        if self._engine is None:
            return
        enabled = self.bypass_btn.isChecked()
        self._engine.set_bypass(enabled)
        if enabled:
            self.status_pill.set_state("Bypassed", "warn")
            self.status_detail.setText("Bypassed · the raw microphone is being sent")
        else:
            self.status_pill.set_state("Live", "ok")

    def _tick(self) -> None:
        engine = self._engine
        if engine is None:
            return
        stats = engine.snapshot()
        self.input_meter.set_level(stats.input_rms)
        self.output_meter.set_level(stats.output_rms)
        if stats.error:
            if stats.error != self._error_shown:
                self._error_shown = stats.error
                self._stop_engine()
                QMessageBox.critical(
                    self,
                    "Audio stopped",
                    f"{stats.error}\n\nDetails are in the log file:\n{logs_dir() / 'vox.log'}",
                )
            return
        if stats.bypassed:
            self.status_pill.set_state("Bypassed", "warn")
            self.status_detail.setText("Bypassed · the raw microphone is being sent")
        else:
            self.status_pill.set_state("Live", "ok")
            if stats.rtf > 0:
                realtime = 1.0 / stats.rtf
                text = (
                    f"Live · {stats.infer_ms:.0f} ms per block · "
                    f"{realtime:.1f}x real time"
                )
                if stats.rtf > 1.02:
                    text += " · falling behind"
                wanted = "Warn" if stats.rtf > 1.02 else "Muted"
                if self.status_detail.objectName() != wanted:
                    self.status_detail.setObjectName(wanted)
                    self._restyle(self.status_detail)
                self.status_detail.setText(text)
            else:
                self.status_detail.setText("Live · warming up")
        self._update_latency_hint()

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # ----------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        self._timer.stop()
        worker = self._start_worker
        if worker is not None and worker.isRunning():
            worker.wait(6000)
            if worker.result is not None and self._engine is None:
                worker.result.stop()
        if self._engine is not None:
            self._engine.stop()
            self._engine = None
        if self._model is not None:
            self._model.unload()
        self._sync_settings_from_ui()
        save_settings(self.settings)
        event.accept()
