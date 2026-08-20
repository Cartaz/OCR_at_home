"""Smoke test QML: Main.qml deve essere caricabile in offscreen."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication


class DummyBackend(QObject):
    @Property(int, constant=True)
    def initialWindowWidth(self): return 800
    @Property(int, constant=True)
    def initialWindowHeight(self): return 600
    @Property(bool, constant=True)
    def busy(self): return False
    @Property(bool, constant=True)
    def modelLoading(self): return False
    @Property(bool, constant=True)
    def ocrRunning(self): return False
    @Property(bool, constant=True)
    def batchRunning(self): return False
    @Property(int, constant=True)
    def languageIndex(self): return 0
    @Property(bool, constant=True)
    def preprocessingEnabled(self): return True
    @Property("QVariantList", constant=True)
    def devices(self): return []
    @Property(int, constant=True)
    def deviceIndex(self): return 0
    @Property(str, constant=True)
    def ocrFileName(self): return "Nessun file selezionato"
    @Property(str, constant=True)
    def ocrFilePath(self): return ""
    @Property(str, constant=True)
    def ocrText(self): return ""
    @Property(str, constant=True)
    def ocrStatusText(self): return "Pronto"
    @Property(str, constant=True)
    def ocrStatusColor(self): return "#6F757C"
    @Property(str, constant=True)
    def ocrPageProgress(self): return ""
    @Property(str, constant=True)
    def batchDropText(self): return ""
    @Property(str, constant=True)
    def batchText(self): return ""
    @Property(str, constant=True)
    def batchStatusText(self): return "Pronto"
    @Property(str, constant=True)
    def batchStatusColor(self): return "#6F757C"
    @Property(str, constant=True)
    def batchProgressText(self): return ""
    @Property(str, constant=True)
    def batchCountText(self): return ""

    @Slot()
    def forceQuit(self): pass
    @Slot()
    def minimizeToTray(self): pass
    @Slot()
    def startOcr(self): pass
    @Slot()
    def stopOcr(self): pass
    @Slot()
    def refreshDevices(self): pass
    @Slot()
    def clearOcr(self): pass
    @Slot()
    def saveOcr(self): pass
    @Slot()
    def startBatch(self): pass
    @Slot()
    def stopBatch(self): pass
    @Slot()
    def clearBatch(self): pass
    @Slot()
    def saveBatch(self): pass
    @Slot()
    def chooseOcrFile(self): pass
    @Slot()
    def chooseBatchFiles(self): pass
    @Slot()
    def handleWindowClose(self): pass
    @Slot(int)
    def setLanguageIndex(self, _index): pass
    @Slot(bool)
    def setPreprocessing(self, _enabled): pass
    @Slot(int)
    def setDeviceIndex(self, _index): pass
    @Slot("QVariantList")
    def setBatchDroppedUrls(self, _urls): pass


def test_main_qml_loads() -> None:
    app = QApplication.instance() or QApplication([])
    engine = QQmlApplicationEngine()
    backend = DummyBackend()
    engine.rootContext().setContextProperty("backend", backend)
    qml = Path(__file__).parents[2] / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    assert engine.rootObjects(), "Main.qml non è caricabile"
    for obj in engine.rootObjects():
        obj.close()
    engine.deleteLater()
    _ = app


def test_main_qml_keeps_safe_controls_available_during_model_load() -> None:
    text = (Path(__file__).parents[2] / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "enabled: !backend.busy && !backend.modelLoading" in text
    assert "backend.ocrRunning || backend.modelLoading" in text
    assert "backend.batchRunning || backend.modelLoading" in text
