"""Behavior of the QML view-state adapter (ui.backend.UiBackend)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QImage

from config.settings import Settings
from core.app_controller import OP_BATCH, OP_IDLE, OP_MODEL_LOADING, OP_OCR
from core.event_bus import EventBus
from core.input_staging import InputStaging
from ui.backend import UiBackend


class FakeController:
    def __init__(self, *, model_ready: bool = True) -> None:
        self.operation = OP_IDLE
        self.model_ready = model_ready
        self.settings = Settings(output_dir="/tmp/glm-ocr-test-output")
        self.calls: list[tuple] = []

    def __getattr__(self, name: str):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in {"request_save_single_result", "request_save_single_pdf_pages"}:
                return "req-1"
            if name == "run_batch_or_queue":
                return (False, None)
            return False

        return record

    def update_settings(self, **overrides) -> None:
        self.calls.append(("update_settings", (), overrides))
        self.settings = self.settings.with_(**overrides)


@pytest.fixture
def make_backend(qapp, tmp_path):
    created: list[UiBackend] = []

    def make(controller: FakeController | None = None, **kwargs) -> tuple[UiBackend, FakeController]:
        controller = controller or FakeController()
        kwargs.setdefault("input_staging", InputStaging(tmp_path / "inputs", max_bytes=1024 * 1024))
        kwargs.setdefault("quit_application", lambda: controller.calls.append(("quit", (), {})))
        backend = UiBackend(controller, **kwargs)
        created.append(backend)
        return backend, controller

    yield make
    for backend in created:
        backend.shutdown()


def _image(tmp_path: Path, name: str = "page.png") -> Path:
    path = tmp_path / name
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    image.save(str(path))
    return path


def _available(backend: UiBackend) -> None:
    EventBus.emit("hardware_detected", {"available": True, "label": "llama.cpp + SYCL0: test"})


def test_start_is_enabled_only_with_backend_and_selection(make_backend, tmp_path) -> None:
    backend, _ = make_backend(FakeController(model_ready=False))
    assert backend.canStartSingle is False
    backend._apply_single_selection(str(_image(tmp_path)))
    assert backend.canStartSingle is False  # backend not detected yet
    _available(backend)
    assert backend.canStartSingle is True
    EventBus.emit("operation_changed", {"operation": OP_MODEL_LOADING})
    assert backend.canStartSingle is False
    assert backend.globalCancelVisible is True
    assert backend.sidebarStatusText == "Caricamento modello"


def test_single_ocr_is_delegated_to_controller_queue_policy(make_backend, tmp_path) -> None:
    backend, controller = make_backend(FakeController(model_ready=False))
    image = _image(tmp_path)
    backend._apply_single_selection(str(image))
    backend.startSingleOcr()
    assert controller.calls[-1][0] == "start_ocr_or_queue"
    assert controller.calls[-1][1] == (image.resolve(),)


def test_completed_ocr_enables_saving_for_that_source_only(make_backend, tmp_path) -> None:
    backend, controller = make_backend()
    image = str(_image(tmp_path).resolve())
    backend._apply_single_selection(image)
    EventBus.emit("ocr_started", {"mode": "single", "is_pdf": True, "image_path": image})
    assert backend.singleProgressVisible is True
    assert backend.singleProgressLabel == "Preparazione PDF"
    EventBus.emit("pdf_page_completed", {"mode": "single", "page_num": 1, "total_pages": 2, "text": "uno"})
    assert backend.singleText == "--- Pagina 1 ---\nuno"
    EventBus.emit("ocr_completed", {
        "mode": "single", "is_pdf": True, "image_path": image, "time_ms": 1500,
        "text": "--- Pagina 1 ---\nuno\n\n--- Pagina 2 ---\ndue", "pages": ["uno", "due"],
    })
    assert backend.singleMeta == "1.5 s"
    assert backend.canSaveSingle is True and backend.showPageSave is True

    backend.saveSinglePages("md")
    assert controller.calls[-1] == ("request_save_single_pdf_pages", (image, "md"), {})
    assert backend.canSaveSingle is False  # pending until the worker reports back
    EventBus.emit("single_output_saved", {"request_id": "req-1", "kind": "pages", "count": 2, "paths": ["a", "b"]})
    assert backend.canSaveSingle is True
    assert backend.noticeTitle == "Pagine PDF salvate"

    backend._apply_single_selection(str(_image(tmp_path, "other.png").resolve()))
    assert backend.canSaveSingle is False


def test_failed_ocr_shows_urgent_notice_with_details(make_backend) -> None:
    backend, _ = make_backend()
    EventBus.emit("ocr_failed", {"mode": "single", "error": "server down"})
    assert backend.noticeVisible and backend.noticeUrgent
    assert backend.noticeDetails == "server down"
    backend.dismissNotice()
    assert backend.noticeVisible is False


def test_batch_state_machine(make_backend, tmp_path) -> None:
    backend, controller = make_backend()
    _available(backend)
    a, b = str(_image(tmp_path, "a.png").resolve()), str(_image(tmp_path, "b.png").resolve())
    backend._apply_batch_selection([a, b])
    assert backend.batchCountLabel == "2 file selezionati"
    backend.startBatch()
    assert controller.calls[-1][0] == "run_batch_or_queue"

    EventBus.emit("operation_changed", {"operation": OP_BATCH})
    EventBus.emit("batch_started", {"total_tasks": 2})
    assert [row["state"] for row in backend.batchFiles] == ["In elaborazione", "In coda"]
    EventBus.emit("batch_task_completed", {"image_path": a, "text": "A"})
    EventBus.emit("batch_progress", {"completed": 1, "total": 2})
    assert [row["state"] for row in backend.batchFiles] == ["Completato", "In elaborazione"]
    assert backend.batchProgressValue == "1 / 2"
    backend.removeBatchFile(a)  # not allowed while running
    assert len(backend.batchFiles) == 2
    EventBus.emit("batch_cancelled", {})
    assert [row["state"] for row in backend.batchFiles] == ["Completato", "Annullato"]
    assert backend.batchResults == [{"path": a, "name": "a.png", "ok": True, "text": "A"}]

    EventBus.emit("operation_changed", {"operation": OP_IDLE})
    backend.removeBatchFile(a)
    assert [row["path"] for row in backend.batchFiles] == [b]


def test_drop_routes_by_view_and_rejects_while_busy(make_backend, tmp_path) -> None:
    backend, _ = make_backend()
    one = _image(tmp_path, "one.png")
    two = _image(tmp_path, "two.png")
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("x")

    backend.setView("logs")
    backend.acceptDroppedUrls([QUrl.fromLocalFile(str(one)), QUrl.fromLocalFile(str(two))])
    assert backend.view == "batch" and len(backend.batchFiles) == 2

    backend.acceptDroppedUrls([QUrl.fromLocalFile(str(unsupported))])
    assert backend.noticeVisible and "notes.txt" not in backend.singleName

    backend.setView("ocr")
    backend.acceptDroppedUrls([QUrl.fromLocalFile(str(one))])
    assert backend.singleName == "one.png"

    EventBus.emit("operation_changed", {"operation": OP_OCR})
    backend.acceptDroppedUrls([QUrl.fromLocalFile(str(two))])
    assert backend.singleName == "one.png"


def test_clipboard_image_is_staged_as_png(make_backend, tmp_path) -> None:
    backend, _ = make_backend()
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    QGuiApplication.clipboard().setImage(image)
    backend.pasteClipboardImage()
    assert backend.singleName == "Immagine dagli appunti.png"
    assert Path(backend.singlePath).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    QGuiApplication.clipboard().clear()


def test_settings_are_validated_by_the_controller(make_backend) -> None:
    backend, controller = make_backend()
    assert backend.saveSettings({"model_auto_unload_minutes": 30.0, "language": "ignored"}) is True
    assert controller.settings.model_auto_unload_minutes == 30
    assert backend.saveSettings({"output_dir": "relative/path"}) is False
    assert backend.noticeTitle == "Impostazioni non salvate"
    assert controller.settings.output_dir == "/tmp/glm-ocr-test-output"


def test_window_resize_does_not_reset_the_settings_form(make_backend) -> None:
    backend, _ = make_backend()
    emitted: list[int] = []
    backend.settingsChanged.connect(lambda: emitted.append(1))
    EventBus.emit("config_changed", {"window_width": 900, "window_height": 700})
    assert emitted == []
    EventBus.emit("config_changed", {"batch_auto_save": True})
    assert emitted == [1]


def test_model_controls_follow_backend_state(make_backend) -> None:
    backend, controller = make_backend(FakeController(model_ready=False))
    _available(backend)
    assert backend.backendChipText == "Scaricato"
    assert backend.reloadModelLabel == "Carica modello"
    backend.reloadModel()
    assert controller.calls[-1][0] == "request_model_load"
    EventBus.emit("model_loaded", {})
    assert backend.modelReady and backend.backendChipText == "Pronto"
    assert backend.canUnloadModel is True
    backend.unloadModel()
    assert controller.calls[-1][0] == "request_model_unload"


def test_cancel_dispatches_by_operation(make_backend) -> None:
    backend, controller = make_backend()
    for operation, expected in (
        (OP_MODEL_LOADING, "cancel_model_loading"),
        (OP_OCR, "cancel_ocr"),
        (OP_BATCH, "cancel_active_batch"),
    ):
        controller.operation = operation
        backend.cancelOperation()
        assert controller.calls[-1][0] == expected


def test_shutdown_stops_controller_and_staging(make_backend, tmp_path) -> None:
    staging = InputStaging(tmp_path / "inputs", max_bytes=1024)
    backend, controller = make_backend(input_staging=staging)
    staging.stage_png(b"\x89PNG\r\n\x1a\n")
    session = staging.session_dir
    backend.shutdown()
    assert ("shutdown", (), {}) in controller.calls
    assert session is not None and not session.exists()


def test_logs_are_read_as_a_bounded_tail(make_backend, monkeypatch, tmp_path) -> None:
    backend, _ = make_backend()
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"line {i}" for i in range(3000)), encoding="utf-8")
    monkeypatch.setattr("ui.backend.AppMeta.LOG_PATH", log)
    text = backend.readLogs(5000)
    assert text.splitlines()[-1] == "line 2999"
    assert len(text.splitlines()) == 2000


def test_loaded_model_keeps_start_enabled_after_a_failed_probe(make_backend, tmp_path) -> None:
    backend, _ = make_backend()
    EventBus.emit("model_loaded", {})
    EventBus.emit("hardware_detected", {"available": False, "label": "probe failed"})
    backend._apply_single_selection(str(_image(tmp_path)))
    assert backend.canStartSingle is True
    assert backend.canReloadModel is True


def test_window_sizes_below_the_minimum_are_not_persisted(make_backend) -> None:
    backend, controller = make_backend()
    backend.saveWindowSize(300, 900)
    assert not [call for call in controller.calls if call[0] == "update_settings"]
    backend.saveWindowSize(900, 700)
    assert controller.settings.window_width == 900


def test_batch_progress_hides_after_failure(make_backend, qapp) -> None:
    import time as _time

    backend, _ = make_backend()
    EventBus.emit("batch_started", {"total_tasks": 1})
    EventBus.emit("batch_failed", {"error": "x"})
    assert backend.batchProgressVisible is True
    deadline = _time.monotonic() + 2
    while backend.batchProgressVisible and _time.monotonic() < deadline:
        qapp.processEvents()
        _time.sleep(0.02)
    assert backend.batchProgressVisible is False


def test_selecting_a_new_file_clears_the_previous_result(make_backend, tmp_path) -> None:
    backend, _ = make_backend()
    first = str(_image(tmp_path, "a.png").resolve())
    backend._apply_single_selection(first)
    EventBus.emit("ocr_completed", {"mode": "single", "image_path": first, "text": "A", "pages": []})
    assert backend.canCopySingle is True
    backend._apply_single_selection(str(_image(tmp_path, "b.png").resolve()))
    assert backend.singleText == "" and backend.canCopySingle is False


def test_progress_uses_the_friendly_clipboard_name(make_backend, tmp_path) -> None:
    backend, _ = make_backend()
    staged = str(_image(tmp_path, "clipboard-k3j2abcd.png").resolve())
    backend._apply_single_selection(staged, "Immagine dagli appunti.png")
    EventBus.emit("ocr_started", {"mode": "single", "image_path": staged, "is_pdf": False})
    assert backend.singleMeta == "Elaborazione di Immagine dagli appunti.png…"
