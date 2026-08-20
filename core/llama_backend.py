# core/llama_backend.py
"""Backend OCR basato su llama.cpp con modelli GGUF.

Questo modulo implementa il backend primario per l'inferenza OCR.
Usa llama.cpp (tramite llama-server) per eseguire il modello GLM-OCR
in formato GGUF quantizzato, con SYCL nativo per GPU Intel Arc.

Architettura:
- llama-server gira come processo figlio sulla porta 8081
- L'app comunica via API REST (/v1/chat/completions)
- Il server viene avviato/arrestato automaticamente con l'app
- GPU offload completo: tutti i layer su GPU
- SYCL come backend primario, Vulkan come fallback

IMPORTANTE: il binary SYCL vive in .venv/bin/ e le librerie condivise
in .venv/lib/. LD_LIBRARY_PATH deve includere .venv/lib/ per permettere
al runtime linker di trovare libggml-sycl.so, libggml.so, etc.
Senza questo, llama-server non carica il backend SYCL e ricade su CPU-only.

Requisiti:
- llama.cpp compilato con SYCL (install.sh lo fa automaticamente)
- Modello GGUF: ggml-org/GLM-OCR-GGUF (Q8_0 raccomandato)
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from config.constants import AppMeta
from core.event_bus import EventBus
from core.exceptions import ModelLoadError
from core.llama_gpu_detect import (
    find_llama_server,
    detect_gpu_backend,
    venv_lib_env,
    GPU_OFFLOAD_ALL_LAYERS,
    GPU_OFFLOAD_PARTIAL_LAYERS,
)
from core.llama_models import ensure_gguf_models
from core.models import OCRResult

logger = logging.getLogger(__name__)

# Configurazione server
LLAMA_SERVER_PORT: int = 8081
LLAMA_SERVER_HOST: str = "127.0.0.1"
LLAMA_SERVER_URL: str = f"http://{LLAMA_SERVER_HOST}:{LLAMA_SERVER_PORT}"

# Contesto e batch size ottimizzati per GLM-OCR su Intel Arc iGPU.
# - Contesto 2048: sufficiente per OCR (immagine 640px + output testo).
#   Contesti più grandi (4096+) causano OOM su iGPU con ~14GB VRAM
#   perché il KV cache per modelli vision è molto grande, e llama-server
#   alloca 4 slot paralleli per default (4 × ctx × kv_size = OOM).
# - Batch 512: bilanciato per evitare overflow durante il prefill
#   dei token vision del modello multimodale.
# - Parallel 1: OCR è sequenziale, non serve parallelismo. Con n_parallel=4
#   il server alloca 4 KV cache indipendenti → OOM garantito su iGPU.
CONTEXT_SIZE: int = 4096
BATCH_SIZE: int = 1024
N_PARALLEL: int = 1

# Numero massimo di tentativi automatici se llama-server crasha
# durante un'inferenza OCR (es. OOM sporadico).
MAX_OCR_RETRIES: int = 1


class LlamaServerBackend:
    """Backend OCR che usa llama-server con modello GGUF.

    Gestisce il ciclo di vita del server llama.cpp come processo figlio
    e comunica tramite API REST per l'inferenza OCR.
    """

    def __init__(self) -> None:
        """Inizializza il backend con stato non avviato."""
        self._process: subprocess.Popen | None = None
        self._server_path: str | None = None
        self._model_paths: dict[str, Path] = {}
        self._initialized: bool = False
        self._server_url: str = LLAMA_SERVER_URL
        self._gpu_layers: int = 0
        self._gpu_backend: str = "cpu"
        self._log_file: Any = None
        self._pdf_pages_streamed: bool = False  # True se le pagine sono già state trasmesse via EventBus

    @property
    def is_initialized(self) -> bool:
        """Indica se il backend è stato inizializzato."""
        return self._initialized

    @property
    def gpu_layers(self) -> int:
        """Numero di layer offloadati su GPU (0 = CPU only)."""
        return self._gpu_layers

    @property
    def gpu_backend(self) -> str:
        """Backend GPU attivo ('sycl', 'vulkan' o 'cpu')."""
        return self._gpu_backend

    @property
    def is_server_running(self) -> bool:
        """Verifica se il server llama.cpp è in esecuzione e risponde."""
        try:
            req = Request(f"{self._server_url}/health")
            with urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _check_server_alive(self) -> None:
        """Verifica che il processo llama-server sia ancora vivo.

        Se il processo è terminato, legge le ultime righe del log
        per fornire informazioni sul crash.

        Raises:
            ModelLoadError: Se il processo è morto, con dettagli dal log.
        """
        if self._process is not None and self._process.poll() is not None:
            exit_code = self._process.returncode
            log_tail = ""
            try:
                log_path = AppMeta.CONFIG_DIR / "llama-server.log"
                if log_path.exists():
                    log_tail = log_path.read_text()[-3000:]
            except Exception:
                pass
            self._process = None
            self._initialized = False
            raise ModelLoadError(
                "llama-server",
                f"llama-server è crashato (codice uscita: {exit_code}).\n"
                f"Ultimo log:\n{log_tail}",
            )

    def initialize(self) -> None:
        """Inizializza il backend: trova llama-server, scarica modelli, avvia server.

        Raises:
            ModelLoadError: Se l'inizializzazione fallisce.
        """
        logger.info("Inizializzazione backend llama.cpp...")

        self._server_path = find_llama_server()
        if not self._server_path:
            raise ModelLoadError(
                "llama-server",
                "llama-server non trovato. Installa llama.cpp:\n"
                "  sudo pacman -S llama.cpp\n"
                "  oppure: yay -S llama.cpp\n"
                "  oppure compila da: https://github.com/ggml-org/llama.cpp",
            )
        logger.info("llama-server trovato: %s", self._server_path)

        self._model_paths = ensure_gguf_models()
        self._gpu_layers, self._gpu_backend = detect_gpu_backend()
        self._start_server_with_fallback()
        self._initialized = True
        logger.info("Backend llama.cpp inizializzato con successo")

    def _start_server_with_fallback(self) -> None:
        """Avvia llama-server con fallback progressivo GPU -> CPU.

        NOTA: flash attention e' disabilitato per tutti i profili perche'
        causa crash noti con i modelli vision GLM (v. GitHub #21550, #17422).
        Il vision encoder usa attention bidirezionale incompatibile con
        i kernel flash-attn di llama.cpp.

        La sequenza di fallback è:
        1. GPU full offload (SYCL/Vulkan) con --parallel 1 --cache-ram 0
        2. GPU partial offload (20 layer) se full offload fallisce
        3. CPU-only come ultima risorsa
        """
        configs: list[dict[str, Any]] = []

        if self._gpu_layers > 0 and self._gpu_backend != "cpu":
            configs.append({
                "gpu_layers": GPU_OFFLOAD_ALL_LAYERS,
                "gpu_backend": self._gpu_backend,
                "flash_attn": False,
                "label": f"GPU full offload ({self._gpu_backend.upper()})",
            })
            configs.append({
                "gpu_layers": GPU_OFFLOAD_PARTIAL_LAYERS,
                "gpu_backend": self._gpu_backend,
                "flash_attn": False,
                "label": f"GPU partial offload ({self._gpu_backend.upper()})",
            })

        configs.append({
            "gpu_layers": 0, "gpu_backend": "cpu",
            "flash_attn": False, "label": "CPU-only",
        })

        last_error: ModelLoadError | None = None
        for i, config in enumerate(configs):
            try:
                logger.info("Tentativo %d/%d: %s", i + 1, len(configs), config["label"])
                self._start_server(
                    gpu_layers=config["gpu_layers"],
                    gpu_backend=config["gpu_backend"],
                    flash_attn=config["flash_attn"],
                )
                self._gpu_layers = config["gpu_layers"]
                self._gpu_backend = config["gpu_backend"]
                logger.info("Server avviato: %s", config["label"])
                return
            except ModelLoadError as exc:
                last_error = exc
                logger.warning("Tentativo %d fallito: %s", i + 1, str(exc)[:200])
                self._stop_server()

        raise ModelLoadError(
            "llama-server",
            f"Impossibile avviare llama-server dopo {len(configs)} tentativi. "
            f"Ultimo errore: {last_error}",
        )

    def _start_server(
        self, gpu_layers: int = 0, gpu_backend: str = "cpu", flash_attn: bool = False,
    ) -> None:
        """Avvia llama-server come processo figlio.

        Args:
            gpu_layers: Numero di layer da offloadare su GPU.
            gpu_backend: Tipo di backend GPU ("sycl", "vulkan", "cpu").
            flash_attn: Se usare flash attention (mai con modelli vision GLM).

        Raises:
            ModelLoadError: Se il server non può essere avviato.
        """
        if self._process is not None and self._process.poll() is None:
            return

        main_model = self._model_paths.get("main")
        mmproj_model = self._model_paths.get("mmproj")

        if not main_model or not main_model.exists():
            raise ModelLoadError("llama-server", f"Modello GGUF non trovato: {main_model}")

        n_threads = self._optimal_thread_count()
        cmd = [
            self._server_path, "-m", str(main_model),
            "--port", str(LLAMA_SERVER_PORT), "--host", LLAMA_SERVER_HOST,
            "-ngl", str(gpu_layers), "-c", str(CONTEXT_SIZE),
            "-b", str(BATCH_SIZE), "-t", str(n_threads),
            "--parallel", str(N_PARALLEL),
            "--cache-ram", "0",
            "--metrics",
        ]

        if mmproj_model and mmproj_model.exists():
            cmd.extend(["--mmproj", str(mmproj_model)])
        # flash-attn disabilitato per modelli vision GLM — causa crash

        # CRITICO: costruisce l'ambiente con LD_LIBRARY_PATH che include .venv/lib/
        # Senza questo, il dynamic linker non trova libggml-sycl.so e il
        # server ricade su CPU-only anche se compilato con SYCL.
        env = venv_lib_env()

        if gpu_backend == "sycl" and gpu_layers > 0:
            env["GGML_SYCL"] = "1"
            env["ONEAPI_DEVICE_SELECTOR"] = "level_zero:0"
            env["ZES_ENABLE_SYSMAN"] = "1"

        logger.info("Avvio llama-server: %s", " ".join(cmd))
        EventBus.emit("model_load_progress", {
            "message": f"Avvio llama-server ({'GPU' if gpu_layers > 0 else 'CPU'})...",
        })

        # Redirect stdout/stderr su file per evitare che il buffer
        # subprocess.PIPE (64KB) si riempia e blocchi il processo
        try:
            log_dir = AppMeta.CONFIG_DIR
            log_dir.mkdir(parents=True, exist_ok=True)
            # Trunca il log precedente per evitare file enormi
            log_path = log_dir / "llama-server.log"
            if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
                log_path.unlink()
            self._log_file = open(log_path, "a")
            self._process = subprocess.Popen(
                cmd,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except Exception as exc:
            raise ModelLoadError("llama-server", f"Impossibile avviare: {exc}") from exc

        max_wait = 90
        start = time.perf_counter()
        while time.perf_counter() - start < max_wait:
            if self._process.poll() is not None:
                stderr = ""
                try:
                    if log_path.exists():
                        stderr = log_path.read_text()[-2000:]
                except Exception:
                    pass
                raise ModelLoadError(
                    "llama-server",
                    f"Terminato con codice {self._process.returncode}.\nLog: {stderr}",
                )
            if self.is_server_running:
                logger.info("llama-server pronto in %.1fs", time.perf_counter() - start)
                return
            time.sleep(0.5)

        self._stop_server()
        raise ModelLoadError("llama-server", f"Non ha risposto entro {max_wait}s")

    @staticmethod
    def _optimal_thread_count() -> int:
        """Calcola il numero ottimale di thread per l'inferenza.

        Returns:
            Numero di thread ottimale per il CPU corrente.
        """
        try:
            n_phys = os.cpu_count() or 8
            try:
                with open("/proc/cpuinfo", "r") as f:
                    cpuinfo = f.read()
                core_ids: set[str] = set()
                for line in cpuinfo.split("\n"):
                    if line.startswith("core id"):
                        core_ids.add(line.split(":")[1].strip())
                if core_ids:
                    n_phys = len(core_ids)
            except Exception:
                pass
            return max(4, n_phys - 2)
        except Exception:
            return 6

    def _stop_server(self) -> None:
        """Ferma il processo llama-server con fallback pkill.

        La sequenza di arresto è:
        1. terminate() — segnale SIGTERM al processo figlio
        2. kill() — se non termina entro 5 secondi
        3. pkill llama-server — fallback per processi orfani o zombie
        """
        try:
            if self._process is not None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=3)
        except Exception as exc:
            logger.warning("Errore arresto llama-server (processo): %s", exc)
        finally:
            self._process = None
            if self._log_file is not None:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None

        # Fallback: pkill per garantire che nessun llama-server rimanga attivo.
        # Copre il caso in cui il processo figlio sia diventato zombie,
        # sia stato adottato da init, o il Popen abbia perso il riferimento.
        try:
            subprocess.run(
                ["pkill", "llama-server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except Exception:
            pass

        logger.info("llama-server arrestato")

    # ── OCR Processing ─────────────────────────────────────────────

    def process_image(self, image_path: Path) -> OCRResult:
        """Elabora un'immagine o un PDF tramite llama-server.

        Per i PDF, ogni pagina viene trasmessa incrementalmente via
        EventBus (evento ``pdf_page_completed``) man mano che viene
        completata, consentendo alla GUI di mostrare i risultati
        come checkpoint. L'evento ``ocr_completed`` finale non
        include il testo se le pagine sono già state trasmesse.

        Se llama-server crasha durante l'inferenza (es. OOM), tenta
        automaticamente un riavvio del server con contesto ridotto e
        riprova una volta prima di arrendersi.

        Args:
            image_path: Percorso del file immagine o PDF.

        Returns:
            OCRResult con testo estratto e metadati.

        Raises:
            ModelLoadError: Se il server non è inizializzato o il retry fallisce.
        """
        from core.image_utils import is_pdf
        from core.llama_ocr_api import ocr_single_image, ocr_pdf

        if not self._initialized:
            raise ModelLoadError("llama-server", "Server non inizializzato")

        # Verifica che il server sia ancora vivo prima di procedere
        self._check_server_alive()
        if not self.is_server_running:
            raise ModelLoadError("llama-server", "Server non in esecuzione")

        is_pdf_file = is_pdf(image_path)
        self._pdf_pages_streamed = False  # Reset flag per questa elaborazione

        task_id = image_path.stem
        EventBus.emit("ocr_started", {"task_id": task_id, "is_pdf": is_pdf_file})
        start_time = time.perf_counter()

        last_exc: Exception | None = None
        for attempt in range(MAX_OCR_RETRIES + 1):
            try:
                if is_pdf_file:
                    # ocr_pdf() emette pdf_page_completed per ogni pagina
                    text, confidence = ocr_pdf(image_path, self._server_url)
                    self._pdf_pages_streamed = True
                else:
                    text, confidence = ocr_single_image(image_path, self._server_url)

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                device_label = "CPU (llama.cpp)"
                if self._gpu_layers > 0:
                    if self._gpu_layers >= GPU_OFFLOAD_ALL_LAYERS:
                        device_label = f"GPU {self._gpu_backend.upper()} (llama.cpp)"
                    else:
                        device_label = f"GPU+CPU {self._gpu_backend.upper()} (llama.cpp)"
                # Nota: _pdf_pages_streamed viene aggiornato dentro il blocco
                # try sottostante in base a ocr_pdf() / ocr_single_image().

                result = OCRResult(
                    text=text, confidence=confidence,
                    processing_time_ms=elapsed_ms, device_used=device_label,
                )
                # Per i PDF, le pagine sono già state trasmesse pagina per
                # pagina via EventBus, quindi non includere il testo completo
                # nell'evento ocr_completed per evitare duplicazione nella GUI.
                EventBus.emit("ocr_completed", {
                    "task_id": task_id,
                    "text": "" if self._pdf_pages_streamed else text,
                    "confidence": confidence,
                    "time_ms": elapsed_ms,
                    "is_pdf": is_pdf_file,
                    "pages_streamed": self._pdf_pages_streamed,
                })
                return result

            except Exception as exc:
                last_exc = exc
                logger.error(
                    "Errore OCR per %s (tentativo %d/%d): %s",
                    image_path, attempt + 1, MAX_OCR_RETRIES + 1, exc,
                )

                # Controlla se il server è crashato
                server_crashed = (
                    self._process is not None and self._process.poll() is not None
                ) or "Remote end closed connection" in str(exc)

                if server_crashed and attempt < MAX_OCR_RETRIES:
                    logger.warning(
                        "llama-server sembra essere crashato. "
                        "Tentativo di riavvio automatico (tentativo %d/%d)...",
                        attempt + 1, MAX_OCR_RETRIES,
                    )
                    self._stop_server()
                    # Riavvia il server
                    try:
                        self._start_server_with_fallback()
                        if not self.is_server_running:
                            raise ModelLoadError("llama-server", "Server non ripartito dopo crash")
                        logger.info("Server riavviato con successo, ritento l'OCR")
                        continue
                    except ModelLoadError as restart_exc:
                        logger.error("Impossibile riavviare il server: %s", restart_exc)
                        break
                else:
                    # Errore non legato a crash o tentativi esauriti
                    break

        EventBus.emit("ocr_failed", {"task_id": task_id, "error": str(last_exc)})
        raise ModelLoadError(
            "llama-server",
            f"OCR fallito per {image_path.name}: {last_exc}",
        )

    def shutdown(self) -> None:
        """Arresta il backend e ferma llama-server."""
        self._stop_server()
        self._initialized = False
        logger.info("Backend llama.cpp arrestato")
