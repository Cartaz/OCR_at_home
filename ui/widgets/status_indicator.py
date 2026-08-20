# ui/widgets/status_indicator.py
"""Indicatore di stato animato — punto colorato con pulsazione.

Mostra visivamente lo stato di un processo in background tramite
un punto colorato (diametro 8px) con animazione pulsante per i
processi attivi (opacity oscillante tra 0.5 e 1.0).

Classes:
    StatusIndicator: Widget indicatore di stato animato.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QColor, QBrush
from PySide6.QtWidgets import QWidget

from config.theme import ThemeColors
from config.constants import UIConstraints


class StatusIndicator(QWidget):
    """Indicatore di stato animato — punto colorato con pulsazione.

    L'animazione pulsante mostra visivamente lo stato del processo:
    uno stato attivo ha opacity oscillante, uno stato inattivo è fisso.

    Attributes:
        State: Enum degli stati supportati.
    """

    class State(Enum):
        """Stati visivi dell'indicatore."""

        RUNNING = "running"
        STOPPED = "stopped"
        ERROR = "error"
        PAUSED = "paused"
        BUFFERING = "buffering"
        LOADING = "loading"
        IDLE = "idle"
        COMPLETED = "completed"

    # Mappa stati → colori del tema
    _STATE_COLORS: dict[State, str] = {
        State.RUNNING: ThemeColors.STATUS_RUNNING,
        State.STOPPED: ThemeColors.STATUS_STOPPED,
        State.ERROR: ThemeColors.STATUS_ERROR,
        State.PAUSED: ThemeColors.STATUS_PAUSED,
        State.BUFFERING: ThemeColors.STATUS_BUFFERING,
        State.LOADING: ThemeColors.STATUS_LOADING,
        State.IDLE: ThemeColors.STATUS_STOPPED,
        State.COMPLETED: ThemeColors.STATUS_COMPLETED,
    }

    # Stati che richiedono animazione pulsante
    _ANIMATED_STATES = {State.RUNNING, State.BUFFERING, State.LOADING}

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inizializza l'indicatore di stato.

        Args:
            parent: Widget genitore.
        """
        super().__init__(parent)
        self._state = self.State.IDLE
        self._opacity = 1.0
        self._color = QColor(self._STATE_COLORS[self.State.IDLE])

        diameter = UIConstraints.STATUS_DOT_DIAMETER
        self.setFixedSize(diameter, diameter)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(50)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_direction = 1
        self._pulse_step = 0

    def set_state(self, state: State) -> None:
        """Aggiorna lo stato visivo dell'indicatore.

        Args:
            state: Nuovo stato del processo.
        """
        self._state = state
        color_hex = self._STATE_COLORS.get(state, ThemeColors.STATUS_STOPPED)
        self._color = QColor(color_hex)
        self._opacity = 1.0

        if state in self._ANIMATED_STATES:
            self._pulse_step = 0
            self._pulse_direction = 1
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _pulse_tick(self) -> None:
        """Aggiorna l'opacity per l'animazione pulsante."""
        period_ms = ThemeColors.ANIM_PULSE_PERIOD_MS
        steps = period_ms // self._pulse_timer.interval()
        delta = 0.5 / steps
        self._opacity += delta * self._pulse_direction

        if self._opacity >= 1.0:
            self._opacity = 1.0
            self._pulse_direction = -1
        elif self._opacity <= 0.5:
            self._opacity = 0.5
            self._pulse_direction = 1

        self.update()

    def paintEvent(self, event) -> None:
        """Disegna il punto colorato con l'opacity corrente."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(self._color)
        color.setAlphaF(self._opacity)

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)

        diameter = UIConstraints.STATUS_DOT_DIAMETER
        painter.drawEllipse(0, 0, diameter, diameter)
        painter.end()
