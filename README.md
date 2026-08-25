# GLM OCR

GLM OCR is a local desktop OCR application for Linux. The desktop shell uses PySide6/Qt6 with a local HTML/CSS/vanilla-JavaScript frontend connected to Python through QWebChannel. OCR inference is performed by an app-owned `llama-server` built with SYCL and the GLM-OCR GGUF model.

## Runtime assumptions

The supported production path is currently:

- Linux desktop, first-class CachyOS/Arch Linux;
- Python 3.12 or newer;
- Intel GPU exposed through SYCL/Level Zero;
- Intel oneAPI available at `/opt/intel/oneapi/setvars.sh` when `llama-server` must be built;
- local `llama-server` only, bound to `127.0.0.1` and owned by this application;
- no CPU or Vulkan inference fallback.

The installer pins the llama.cpp revision used by the project, builds a SYCL `llama-server` when necessary, verifies that it exposes a SYCL device, and downloads/verifies the required GGUF model files.

## Install

From a clean checkout:

```bash
chmod +x install.sh
./install.sh
```

`install.sh` resolves the repository root from its own location, so it can be invoked from another working directory. It creates or reuses `.venv`, installs the Python requirements, prepares the SYCL runtime, verifies the model files, and installs a per-user desktop entry.

## Launch

```bash
.venv/bin/python main.py
```

Do not open `ui/web/index.html` directly in a browser: the frontend expects the QWebChannel object provided by `main.py`.

## Application data

GLM OCR keeps source code and user/runtime data separate. By default:

- settings: `${XDG_CONFIG_HOME:-~/.config}/glm-ocr/settings.json`;
- application log: `${XDG_CONFIG_HOME:-~/.config}/glm-ocr/glm-ocr.log`;
- llama-server log: `${XDG_CONFIG_HOME:-~/.config}/glm-ocr/llama-server.log`;
- GGUF model cache: `~/.cache/glm-ocr/models/gguf`;
- OCR output: `~/Documents/glm-ocr-output` unless changed in Settings.

Malformed or older settings files are migrated or replaced by safe defaults rather than crashing startup.

## Current behavior

The application supports single-image/PDF OCR and sequential batch OCR, cancellation, progress events, manual `.txt`/`.md` result saving, optional automatic batch saving, per-page PDF output, model unload/reload, optional lazy model startup, idle auto-unload, hardware refresh, local logs, and deterministic shutdown of the app-owned llama-server process group.

The frontend is local-only. Remote content access is disabled and HTTP/HTTPS navigations are delegated to the system browser rather than loaded inside the application WebEngine view.

## Tests

The repository includes deterministic unit/integration tests for core logic, controller coordination, settings, cancellation, external-process lifecycle, bridge behavior, shutdown paths, benchmark helpers, and an offscreen Qt WebEngine smoke test.

Canonical validation is:

```bash
.venv/bin/python -m compileall -q main.py config core ui tests
.venv/bin/python -m pytest
```

The real-world OCR benchmark under `tests/benchmark/` is hardware-backed and is intentionally separate from ordinary CI inference. See `tests/benchmark/README.md` and `tests/benchmark/REALWORLD.md` before running it.

## Troubleshooting

If startup reports that the backend is unavailable, run `./install.sh` again and check that `.venv/bin/llama-server --list-devices` exposes a SYCL device. Detailed diagnostics are written to the application and llama-server logs listed above.

If the model files are missing, the installer will verify/download them through the project model-management code. The application does not silently switch to another compute backend when SYCL is unavailable.

## Development direction

`ROADMAP.md` is the persistent implementation plan. Feature completion requires passing tests and preserving clear ownership boundaries between `core/`, the Qt/QWebChannel shell, and `ui/web/`; measured OCR benchmark evidence is required before production prompt/pipeline/runtime defaults are changed.
