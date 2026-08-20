#!/usr/bin/env bash
# Installazione locale SYCL-only di GLM OCR per CachyOS/Arch Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CACHE_DIR="$SCRIPT_DIR/.cache"
LLAMA_SRC="$CACHE_DIR/llama.cpp"
LLAMA_BUILD="$LLAMA_SRC/build-glm-ocr-sycl"
LLAMA_CPP_REPO="https://github.com/ggml-org/llama.cpp.git"
LLAMA_CPP_COMMIT="07822bddf80d73f1168e592c52e69caaff820f9c"
APP_ID="com.glm-ocr.app"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf '\nATTENZIONE: %s\n' "$*" >&2; }

require_project_files() {
    local missing=0
    local relative
    for relative in \
        requirements.txt \
        main.py \
        core/__init__.py \
        core/llama_models.py \
        config/__init__.py \
        config/constants.py
    do
        if [[ ! -f "$SCRIPT_DIR/$relative" ]]; then
            warn "File applicativo mancante: $relative"
            missing=1
        fi
    done
    if [[ "$missing" -ne 0 ]]; then
        warn "Albero sorgente incompleto: estrai l'archivio completo/repair nella root OCR_at_home."
        return 1
    fi
}

find_python() {
    local candidate
    for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
            then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

require_project_files

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

venv_llama_sycl_works() {
    [[ -x "$VENV_DIR/bin/llama-server" ]] || return 1
    local output
    if ! output="$(
        ZES_ENABLE_SYSMAN=1 \
        ONEAPI_DEVICE_SELECTOR=level_zero:0 \
        LD_LIBRARY_PATH="$VENV_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
            "$VENV_DIR/bin/llama-server" --list-devices 2>&1
    )"; then
        return 1
    fi
    grep -Eiq '(^|[[:space:]])SYCL[0-9]+[[:space:]]*:' <<<"$output"
}

show_sycl_devices() {
    ZES_ENABLE_SYSMAN=1 \
    ONEAPI_DEVICE_SELECTOR=level_zero:0 \
    LD_LIBRARY_PATH="$VENV_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$VENV_DIR/bin/llama-server" --list-devices
}

build_sycl_llama() {
    if [[ ! -f /opt/intel/oneapi/setvars.sh ]]; then
        warn "Intel oneAPI non trovato: impossibile costruire il backend SYCL."
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

    # Gli script oneAPI usano variabili opzionali non sempre definite: non
    # abilitiamo nounset nel sottoprocesso che esegue setvars.sh.
    if ! bash -c "
        set -eo pipefail
        export OCL_ICD_FILENAMES=\"\${OCL_ICD_FILENAMES:-}\"
        export ZES_ENABLE_SYSMAN=1
        source /opt/intel/oneapi/setvars.sh >/dev/null
        cmake -S '$LLAMA_SRC' -B '$LLAMA_BUILD' \\
            -DGGML_SYCL=ON \\
            -DCMAKE_C_COMPILER=icx \\
            -DCMAKE_CXX_COMPILER=icpx \\
            -DCMAKE_BUILD_TYPE=Release \\
            -DLLAMA_OPENSSL=OFF
        cmake --build '$LLAMA_BUILD' --config Release --target llama-server -j'$jobs'
    "; then
        warn "Compilazione llama.cpp SYCL fallita."
        return 1
    fi

    local server="$LLAMA_BUILD/bin/llama-server"
    if [[ ! -x "$server" ]]; then
        warn "Build terminata senza produrre llama-server."
        return 1
    fi

    mkdir -p "$VENV_DIR/bin" "$VENV_DIR/lib"
    install -m755 "$server" "$VENV_DIR/bin/llama-server"

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
        warn "Nessuna libreria condivisa llama.cpp copiata."
        return 1
    fi

    if ! venv_llama_sycl_works; then
        warn "llama-server è stato compilato ma non espone alcun device SYCL."
        return 1
    fi

    show_sycl_devices
    log "llama-server SYCL installato nel venv"
}

if venv_llama_sycl_works; then
    log "llama-server SYCL già presente e verificato: riuso la build esistente"
    show_sycl_devices
else
    if ! build_sycl_llama; then
        warn "Installazione interrotta: nessun llama-server SYCL funzionante disponibile."
        warn "CPU e Vulkan non sono fallback consentiti da GLM OCR."
        exit 1
    fi
fi

if ! venv_llama_sycl_works; then
    warn "Verifica finale fallita: il venv non espone un device SYCL."
    exit 1
fi

log "Verifica/download modelli GGUF"
(
    cd "$SCRIPT_DIR"
    PROJECT_ROOT="$SCRIPT_DIR" "$VENV_DIR/bin/python" - <<'PY'
import os
import sys

root = os.environ["PROJECT_ROOT"]
if root not in sys.path:
    sys.path.insert(0, root)

from core.llama_models import ensure_gguf_models

paths = ensure_gguf_models()
for kind, path in paths.items():
    print(f"  {kind}: {path}")
PY
)

log "Integrazione desktop utente"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GLM OCR
Comment=Riconoscimento ottico locale con GLM-OCR e llama.cpp SYCL
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

log "Installazione SYCL completata"
printf 'Avvio:\n  %q %q\n' "$VENV_DIR/bin/python" "$SCRIPT_DIR/main.py"
printf 'llama.cpp pin:\n  %s\n' "$LLAMA_CPP_COMMIT"
