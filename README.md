# GLM OCR

GLM OCR is a local desktop OCR application for Linux. The interface is written in Qt Quick (QML) on PySide6; OCR inference is performed by an app-owned `llama-server` built with SYCL and the GLM-OCR GGUF model.

## Runtime assumptions

The supported production path is:

- Linux desktop, first-class CachyOS/Arch Linux;
- Python 3.12 or newer;
- Intel GPU exposed through SYCL/Level Zero;
- Intel oneAPI available at `/opt/intel/oneapi/setvars.sh` when `llama-server` must be built;
- local `llama-server` only, bound to `127.0.0.1` and owned by this application;
- no CPU or Vulkan inference fallback.

## Install

From a clean checkout:

```bash
chmod +x install.sh
./install.sh
```

`install.sh` resolves the repository root from its own location, so it can be invoked from another working directory. It:

- creates or reuses `.venv` and installs `requirements.txt` (only `PySide6-Essentials`: an older `.venv` with the full PySide6/WebEngine stack is cleaned up automatically);
- clones and builds the pinned llama.cpp revision with SYCL under `.cache/` (ignored by git) and verifies that `llama-server --list-devices` exposes a SYCL device;
- downloads the GLM-OCR GGUF files from a pinned Hugging Face revision and verifies their SHA-256;
- installs a per-user desktop entry.

On machines with more than one Intel GPU, export `ONEAPI_DEVICE_SELECTOR` (default `level_zero:0`) before running the installer or the app.

### Arch package (alternative)

`PKGBUILD` builds a `glm-ocr` package from the git repository. It relies on the distribution's `llama-cpp` + `ggml-sycl` packages instead of the llama.cpp revision pinned by `install.sh`, so the inference runtime follows the distribution's updates.

## Launch

```bash
.venv/bin/python main.py
```

## Application data

Source code and user/runtime data are kept separate. By default:

- settings: `${XDG_CONFIG_HOME:-~/.config}/glm-ocr/settings.json`;
- application log: `${XDG_CONFIG_HOME:-~/.config}/glm-ocr/glm-ocr.log`;
- llama-server log: `${XDG_CONFIG_HOME:-~/.config}/glm-ocr/llama-server.log`;
- GGUF model cache: `${XDG_CACHE_HOME:-~/.cache}/glm-ocr/models/gguf`;
- clipboard images staged for OCR: `${XDG_CACHE_HOME:-~/.cache}/glm-ocr/inputs` (removed on exit; leftovers of a crashed session are purged at the next start);
- OCR output: `~/Documents/glm-ocr-output` unless changed in Settings.

A malformed settings file, or a single invalid value in it, falls back to the defaults for the affected fields instead of preventing startup.

## Current behavior

Single-image/PDF OCR and sequential batch OCR, cancellation, progress, manual `.txt`/`.md` saving (also one file per PDF page), optional automatic batch saving, drag & drop, clipboard images (Ctrl+V), model unload/reload, optional lazy model startup, idle auto-unload, hardware refresh, a log viewer, and deterministic shutdown of the app-owned llama-server process group.

The production prompt is GLM-OCR's official `Text Recognition:` task prompt, selected by the canonical real-world benchmark (see `benchmarks/DECISION.md`); llama-server runs with llama.cpp's stock tuning defaults.

The Qt Quick interface uses about half the memory of the former Qt WebEngine one (≈190 MiB PSS in one process versus ≈360 MiB in five, measured idle at 1237×836).

## Development

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`requirements-dev.txt` adds `PySide6-Addons` only for the `qsb` shader compiler, needed when editing the shader. The compiled shader `ui/qml/shaders/neumorphic.frag.qsb` is committed; after editing `neumorphic.frag`, rebuild it with:

```bash
.venv/lib/python3*/site-packages/PySide6/qsb --qt6 -o ui/qml/shaders/neumorphic.frag.qsb ui/qml/shaders/neumorphic.frag
sha256sum ui/qml/shaders/neumorphic.frag | cut -d' ' -f1 > ui/qml/shaders/neumorphic.frag.qsb.source-sha256
```

`qsb` output is not byte-reproducible across machines, so the package records the hash of the source it was built from; a test fails if the source changed without a rebuild.

Layout: `config/` (settings and constants), `core/` (Qt-independent application logic and the llama-server backend), `ui/` (`backend.py` holds all view state and is unit-tested; `qml/` is the thin view), `tests/`, and `benchmarks/` (the hardware-backed real-world benchmark, separate from CI inference: see `benchmarks/README.md`).

## Troubleshooting

If startup reports that the backend is unavailable, run `./install.sh` again and check that `.venv/bin/llama-server --list-devices` lists a `SYCL0:` device. Detailed diagnostics are in the application and llama-server logs listed above. The application never silently switches to another compute backend.

## Development direction

`ROADMAP.md` is the persistent implementation plan and `STRATEGIC_REVIEW.md` records the milestone reviews. Measured benchmark evidence is required before production prompt/pipeline/runtime defaults change.
