#!/usr/bin/env bash
# Installazione locale di GLM OCR per CachyOS/Arch Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CACHE_DIR="$SCRIPT_DIR/.cache"
LLAMA_SRC="$CACHE_DIR/llama.cpp"
LLAMA_BUILD="$LLAMA_SRC/build-glm-ocr-sycl"
LLAMA_CPP_REPO="https://github.com/ggml-org/llama.cpp.git"
# Snapshot fissato per riproducibilità il 2026-08-20. Aggiornare il pin
# intenzionalmente dopo test, non tramite un git pull implicito.
LLAMA_CPP_COMMIT="07822bddf80d73f1168e592c52e69caaff820f9c"
APP_ID="com.glm-ocr.app"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf '\nATTENZIONE: %s\n' "$*" >&2; }

find_python() {
    local candidate
    for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1; then
            "$candidate" - <<'PY' >/dev/null 2>&1 && {
                printf '%s\n' "$candidate"
                return 0
            }
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
        fi
    done
    return 1
}

PYTHON_CMD="$(find_python || true)"
if [[ -z "$PYTHON_CMD" ]]; then
    echo "Serve Python 3.11 o successivo." >&2
    exit 1
fi

log "Ambiente Python"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

build_sycl_llama() {
    if [[ ! -f /opt/intel/oneapi/setvars.sh ]]; then
        warn "Intel oneAPI non trovato: salto la build SYCL locale."
        return 1
    fi

    local command_name
    for command_name in git cmake make; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            warn "$command_name non trovato: impossibile compilare llama.cpp SYCL."
            return 1
        fi
    done

    log "llama.cpp SYCL pinned a $LLAMA_CPP_COMMIT"
    mkdir -p "$CACHE_DIR"
    if [[ ! -d "$LLAMA_SRC/.git" ]]; then
        git clone --filter=blob:none "$LLAMA_CPP_REPO" "$LLAMA_SRC"
    fi

    git -C "$LLAMA_SRC" fetch --depth 1 origin "$LLAMA_CPP_COMMIT"
    git -C "$LLAMA_SRC" checkout --detach --force "$LLAMA_CPP_COMMIT"
    git -C "$LLAMA_SRC" clean -fdx

    rm -rf "$LLAMA_BUILD"
    local jobs
    jobs="$(( ($(nproc) + 1) / 2 ))"
    (( jobs < 1 )) && jobs=1

    bash -c "
        set -euo pipefail
        source /opt/intel/oneapi/setvars.sh >/dev/null
        cmake -S '$LLAMA_SRC' -B '$LLAMA_BUILD' \\
            -DGGML_SYCL=ON \\
            -DCMAKE_C_COMPILER=icx \\
            -DCMAKE_CXX_COMPILER=icpx \\
            -DCMAKE_BUILD_TYPE=Release \\
            -DLLAMA_OPENSSL=OFF
        cmake --build '$LLAMA_BUILD' --config Release --target llama-server -j'$jobs'
    "

    local server="$LLAMA_BUILD/bin/llama-server"
    if [[ ! -x "$server" ]]; then
        warn "Build completata ma llama-server non è stato trovato."
        return 1
    fi

    mkdir -p "$VENV_DIR/bin" "$VENV_DIR/lib"
    install -m755 "$server" "$VENV_DIR/bin/llama-server"

    # Mantiene file e symlink SONAME prodotti dalla build shared.
    local copied=0
    local library
    shopt -s nullglob
    for library in \
        "$LLAMA_BUILD/bin"/libggml*.so* \
        "$LLAMA_BUILD/bin"/libllama*.so* \
        "$LLAMA_BUILD/bin"/libmtmd*.so*
    do
        cp -a "$library" "$VENV_DIR/lib/"
        copied=1
    done
    shopt -u nullglob
    if [[ "$copied" -eq 0 ]]; then
        warn "Nessuna libreria condivisa llama.cpp copiata; verifica la build."
    fi

    LD_LIBRARY_PATH="$VENV_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$VENV_DIR/bin/llama-server" --version >/dev/null

    # --list-devices è l'interfaccia upstream usata anche dall'app per
    # verificare che il backend compilato esponga davvero una GPU SYCL.
    LD_LIBRARY_PATH="$VENV_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$VENV_DIR/bin/llama-server" --list-devices || true

    log "llama-server SYCL installato nel venv"
    return 0
}

if ! build_sycl_llama; then
    if command -v llama-server >/dev/null 2>&1; then
        log "Uso il llama-server di sistema: $(command -v llama-server)"
    else
        warn "Nessun llama-server disponibile. Su Arch/CachyOS installa 'llama-cpp'; per SYCL usa una build compatibile o rilancia dopo aver installato oneAPI."
    fi
fi

log "Verifica/download modelli GGUF"
PYTHONPATH="$SCRIPT_DIR" "$VENV_DIR/bin/python" - <<'PY'
from core.llama_models import ensure_gguf_models
paths = ensure_gguf_models()
for kind, path in paths.items():
    print(f"  {kind}: {path}")
PY

log "Integrazione desktop utente"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GLM OCR
Comment=Riconoscimento ottico locale con GLM-OCR e llama.cpp
Exec=$VENV_DIR/bin/python $SCRIPT_DIR/main.py
Icon=glm-ocr
Terminal=false
Categories=Office;Graphics;
StartupNotify=true
EOF

if [[ -f "$SCRIPT_DIR/assets/icons/glm-ocr.svg" ]]; then
    install -m644 "$SCRIPT_DIR/assets/icons/glm-ocr.svg" "$ICON_DIR/glm-ocr.svg"
fi
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true

log "Installazione completata"
printf 'Avvio:\n  %q %q\n' "$VENV_DIR/bin/python" "$SCRIPT_DIR/main.py"
printf 'llama.cpp pin:\n  %s\n' "$LLAMA_CPP_COMMIT"
