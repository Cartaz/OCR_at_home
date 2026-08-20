# main.py
"""GLM OCR — Punto di ingresso (orchestratore puro).

Inizializza l'applicazione Qt, carica le impostazioni, crea il
controller, la finestra principale e l'icona tray, e avvia il
loop degli eventi. Nessuna logica applicativa in questo file.

Alla chiusura dell'app (normale, SIGINT, SIGTERM o crash), il
server llama.cpp viene automaticamente arrestato tramite:
  1. Catena shutdown Qt (closeEvent → controller.shutdown())
  2. atexit handler (safety net per chiusure anomale)
  3. Signal handlers (SIGINT/SIGTERM per kill da terminale)
  4. Fallback pkill se il processo figlio non risponde

Usage:
    python main.py
"""

from __future__ import annotations

import atexit
import logging
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config.constants import AppMeta
from config.settings import Settings
from core.app_controller import AppController
from ui.main_window import MainWindow
from ui.tray_icon import TrayIcon


def setup_logging() -> None:
    """Configura il logging dell'applicazione nella directory XDG."""
    AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(AppMeta.LOG_PATH, encoding="utf-8"),
        ],
    )


def _kill_orphan_llama_server() -> None:
    """Arresta forzatamente ogni processo llama-server orfano.

    Funzione di sicurezza richiamata da atexit e dai signal handler.
    Usa pkill come fallback per garantire che nessun processo
    llama-server rimanga attivo dopo la chiusura dell'app.
    """
    try:
        subprocess.run(
            ["pkill", "llama-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _signal_handler(signum: int, frame: object) -> None:
    """Gestisce SIGINT/SIGTERM per uno shutdown pulito.

    Prima tenta lo shutdown ordinato del controller (se disponibile),
    poi forza la terminazione di llama-server come safety net.

    Args:
        signum: Numero del segnale ricevuto.
        frame: Stack frame corrente (non usato).
    """
    logger = logging.getLogger("GLM OCR")
    logger.info("Segnale %s ricevuto, arresto in corso...", signum)

    # Tenta shutdown ordinato se il controller è disponibile
    if _controller_ref[0] is not None:
        try:
            _controller_ref[0].shutdown()
        except Exception:
            pass

    # Fallback: forza la terminazione di llama-server
    _kill_orphan_llama_server()
    sys.exit(0)


# Riferimento globale al controller per i signal handler
# (i signal handler non ricevono argomenti custom)
_controller_ref: list[AppController | None] = [None]


def main() -> None:
    """Punto di ingresso dell'applicazione — orchestratore puro."""
    setup_logging()
    logger = logging.getLogger("GLM OCR")
    logger.info("Avvio GLM OCR...")

    settings = Settings.load()
    logger.info("Impostazioni caricate — device=%s, lang=%s",
                settings.default_device, settings.language)

    app = QApplication(sys.argv)
    app.setApplicationName(AppMeta.NAME)
    app.setApplicationDisplayName(AppMeta.NAME)
    app.setOrganizationName(AppMeta.ID)
    app.setQuitOnLastWindowClosed(True)

    controller = AppController(settings=settings)
    _controller_ref[0] = controller  # Per i signal handler

    # Registra atexit handler per garantire l'arresto di llama-server
    # anche in caso di chiusura anomala (crash, eccezione non catturata, ecc.)
    atexit.register(_kill_orphan_llama_server)

    # Registra signal handler per SIGINT (Ctrl+C) e SIGTERM (kill)
    # per garantire shutdown pulito anche da terminale.
    # NOTA: il loop eventi Qt blocca i signal handler nativi del
    # Python finché non torna al loop. Per far sì che SIGINT venga
    # gestito tempestivamente, installiamo un timer che risveglia
    # periodicamente il loop Qt permettendo al signal handler di
    # essere invocato.
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Timer di wakeup per permettere la consegna dei signal al thread
    # principale durante l'esecuzione del loop Qt (50ms, leggero).
    _sigint_timer = QTimer()
    _sigint_timer.timeout.connect(lambda: None)
    _sigint_timer.start(50)

    window = MainWindow(controller=controller)

    # Icona della finestra e del tray
    icon_path = Path(__file__).parent / "assets" / "icons" / "glm-ocr.svg"

    if icon_path.exists():
        window_icon = QIcon(str(icon_path))
        window.setWindowIcon(window_icon)
        app.setWindowIcon(window_icon)

    tray = TrayIcon(
        parent=app,
        icon_path=str(icon_path) if icon_path.exists() else None,
    )
    tray.show()

    tray.show_window_requested.connect(window.show)
    tray.show_window_requested.connect(window.raise_)
    tray.show_window_requested.connect(window.activateWindow)
    tray.connect_start_action(window.on_start)
    tray.connect_stop_action(window.on_stop)
    tray.quit_requested.connect(window.force_quit)

    window.set_tray_icon(tray)
    window.show()

    # Avvia caricamento modello in background
    controller.initialize()

    logger.info("GLM OCR pronto")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
