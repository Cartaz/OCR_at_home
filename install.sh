#!/usr/bin/env bash
# Script di installazione per GLM OCR su CachyOS/Arch Linux
#
# Usa esclusivamente llama.cpp + SYCL come backend per l'OCR.
# llama-server viene compilato con GGML_SYCL=1 per l'accelerazione
# GPU Intel Arc e installato nel venv (.venv/bin/).
#
# Il binary SYCL è protetto da aggiornamenti pacman che sovrascrivono
# /usr/bin/llama-server con la versione CPU-only.
#
# Il modello GGUF (GLM-OCR-Q8_0 + mmproj) viene scaricato durante
# l'installazione (~1.4 GB). Il primo avvio sarà immediato.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_NAME="GLM OCR"
APP_ID="com.glm-ocr.app"

echo "+==================================================+"
echo "|        ${APP_NAME} - Installazione               |"
echo "+==================================================+"
echo ""

# ======================================================================
# FASE 1: Ricerca Python compatibile
# ======================================================================

PYTHON_CMD=""

echo "-- Ricerca Python --"

for py_cmd in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$py_cmd" &>/dev/null; then
        PY_VER=$($py_cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        echo "  Trovato $py_cmd (Python $PY_VER)"
        PYTHON_CMD="$py_cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "  !  NESSUN Python trovato!"
    echo "  Installa Python 3.11+ e ri-esegui questo script."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

echo ""
echo "Python selezionato: $PYTHON_CMD (versione $PYTHON_VERSION)"
echo ""

# ======================================================================
# FASE 2: Creazione ambiente virtuale
# ======================================================================

VENV_DIR="$SCRIPT_DIR/.venv"
if [ -d "$VENV_DIR" ]; then
    echo "Rimozione ambiente virtuale esistente..."
    rm -rf "$VENV_DIR"
fi

echo "Creazione ambiente virtuale con $PYTHON_CMD..."
$PYTHON_CMD -m venv "$VENV_DIR"

# Attiva ambiente virtuale
source "$VENV_DIR/bin/activate"

# Aggiorna pip
pip install --upgrade pip setuptools wheel

# ======================================================================
# FASE 3: Installazione dipendenze
# ======================================================================

echo ""
echo "-- Installazione dipendenze --"

# Dipendenze per UI e funzionalità core (nessun PyTorch o OpenVINO)
pip install "PySide6>=6.6.0"
pip install "Pillow>=10.0.0"
pip install "numpy>=1.26.0"
pip install "huggingface_hub"
pip install "PyMuPDF>=1.24.0"

# ======================================================================
# FASE 4: Compilazione llama.cpp con SYCL
# ======================================================================
# Compila llama-server con SYCL e lo installa nel venv.
# Il binary è self-contained: pacman non lo tocca.

echo ""
echo "-- Compilazione llama.cpp con SYCL --"

# Verifica prerequisiti
if ! command -v cmake &>/dev/null; then
    echo "  Installazione cmake..."
    sudo pacman -S --needed --noconfirm cmake
fi

# Verifica Intel oneAPI
if [ ! -f "/opt/intel/oneapi/setvars.sh" ]; then
    echo "  !  Intel oneAPI non trovato!"
    echo "  Installa con: yay -S intel-oneapi-basekit"
    echo ""
    echo "  Proseguo con la versione CPU-only di llama-server..."
    echo ""
else
    LLAMA_SRC="$SCRIPT_DIR/.cache/llama.cpp"

    # Clone o pull dei sorgenti
    if [ -d "$LLAMA_SRC" ]; then
        echo "  Aggiornamento sorgenti llama.cpp..."
        cd "$LLAMA_SRC" && git pull || true
    else
        echo "  Download sorgenti llama.cpp..."
        mkdir -p "$SCRIPT_DIR/.cache"
        git clone https://github.com/ggml-org/llama.cpp "$LLAMA_SRC"
    fi

    # Build con SYCL
    BUILD_DIR="$LLAMA_SRC/build"
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    echo "  Compilazione con SYCL (può richiedere 5-10 minuti)..."
    bash -c "source /opt/intel/oneapi/setvars.sh && \
        cmake .. -DGGML_SYCL=1 -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx && \
        cmake --build . --config Release -j$(nproc)"

    # Copia il binary nel venv
    if [ -f "$BUILD_DIR/bin/llama-server" ]; then
        cp "$BUILD_DIR/bin/llama-server" "$VENV_DIR/bin/llama-server"
        chmod +x "$VENV_DIR/bin/llama-server"

        # Copia le librerie condivise in .venv/lib/
        # CRITICO: senza queste .so, il binary SYCL non può caricare
        # il backend GPU a runtime (exit code 127)
        mkdir -p "$VENV_DIR/lib"
        for so_pattern in \
            "libggml-sycl.so*" \
            "libggml.so*" \
            "libggml-cpu.so*" \
            "libggml-base.so*" \
            "libllama.so*" \
            "libllama-common.so*" \
            "libllama-server-impl.so*" \
            "libmtmd.so*"
        do
            for so_file in "$BUILD_DIR/bin"/$so_pattern; do
                if [ -f "$so_file" ]; then
                    cp "$so_file" "$VENV_DIR/lib/"
                fi
            done
        done

        # Verifica compilatore
        COMPILER_INFO=$("$VENV_DIR/bin/llama-server" --version 2>&1 | head -5)
        if echo "$COMPILER_INFO" | grep -qi "intelllvm\|intel llvm\|icx"; then
            echo "  OK llama-server con SYCL installato nel venv!"
            echo "    Librerie condivise copiate in $VENV_DIR/lib/"
            echo "    Compilatore: IntelLLVM (SYCL abilitato)"
        else
            echo "  !  llama-server compilato ma compilatore non IntelLLVM"
            echo "    Output: $COMPILER_INFO"
        fi
    else
        echo "  !  Build fallito: bin/llama-server non trovato"
        echo "    L'app userà il binary di sistema (CPU-only)"
    fi

    # Pulizia artefatti di build per risparmiare spazio
    echo "  Pulizia artefatti di build..."
    rm -rf "$BUILD_DIR"
fi

# ======================================================================
# FASE 5: Download modelli GGUF
# ======================================================================

echo ""
echo "-- Download modello GGUF (GLM-OCR Q8_0) --"
echo ""

GGUF_DIR="$HOME/.cache/glm-ocr/models/gguf"
mkdir -p "$GGUF_DIR"

# Modelli da scaricare
GGUF_FILES=("GLM-OCR-Q8_0.gguf" "mmproj-GLM-OCR-Q8_0.gguf")
GGUF_REPO="ggml-org/GLM-OCR-GGUF"
ALL_PRESENT=true

for f in "${GGUF_FILES[@]}"; do
    if [ ! -f "$GGUF_DIR/$f" ]; then
        ALL_PRESENT=false
        break
    fi
done

if [ "$ALL_PRESENT" = true ]; then
    echo "  OK Modelli GGUF già presenti nella cache"
    for f in "${GGUF_FILES[@]}"; do
        SIZE=$(du -h "$GGUF_DIR/$f" | cut -f1)
        echo "    $f ($SIZE)"
    done
else
    echo "  Download modelli GGUF da HuggingFace..."
    echo "  Repo: $GGUF_REPO"
    echo ""

    python -c "
from huggingface_hub import hf_hub_download
import os

repo = '$GGUF_REPO'
local_dir = '$GGUF_DIR'
files = ['GLM-OCR-Q8_0.gguf', 'mmproj-GLM-OCR-Q8_0.gguf']

for f in files:
    path = os.path.join(local_dir, f)
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024*1024)
        print(f'  OK {f} già presente ({size_mb:.0f} MB)')
        continue
    print(f'  Scaricamento {f}...')
    downloaded = hf_hub_download(
        repo_id=repo,
        filename=f,
        local_dir=local_dir,
    )
    import shutil
    dl_path = os.path.join(local_dir, f)
    if os.path.exists(downloaded) and downloaded != dl_path:
        shutil.copy2(downloaded, dl_path)
    size_mb = os.path.getsize(dl_path) / (1024*1024)
    print(f'  OK {f} scaricato ({size_mb:.0f} MB)')
" || {
        echo ""
        echo "  !  Download automatico fallito!"
        echo "  Puoi scaricare i modelli manualmente:"
        echo ""
        echo "    # Modello principale (~0.9 GB)"
        echo "    wget -O $GGUF_DIR/GLM-OCR-Q8_0.gguf \\"
        echo "      'https://huggingface.co/$GGUF_REPO/resolve/main/GLM-OCR-Q8_0.gguf'"
        echo ""
        echo "    # Proiettore multimodale (~0.5 GB)"
        echo "    wget -O $GGUF_DIR/mmproj-GLM-OCR-Q8_0.gguf \\"
        echo "      'https://huggingface.co/$GGUF_REPO/resolve/main/mmproj-GLM-OCR-Q8_0.gguf'"
        echo ""
        echo "  Dopo il download, riavvia l'app."
    }
fi

# ======================================================================
# FASE 6: Verifica GPU Intel
# ======================================================================

echo ""
echo "-- Verifica GPU Intel --"

# Verifica Level Zero loader
if [ -f "/usr/lib/libze_loader.so" ] || [ -f "/usr/lib64/libze_loader.so" ]; then
    echo "  OK Level Zero loader installato"
else
    echo "  !  Level Zero loader non trovato"
    echo "    Installa con: sudo pacman -S level-zero-loader level-zero-headers"
fi

# Verifica Intel Compute Runtime
if command -v ocloc &>/dev/null; then
    echo "  OK Intel Compute Runtime installato (ocloc)"
else
    echo "  !  Intel Compute Runtime non trovato"
    echo "    Installa con: sudo pacman -S intel-compute-runtime"
fi

# Verifica GPU Intel via lspci
if command -v lspci &>/dev/null; then
    if lspci | grep -q "VGA compatible controller: Intel"; then
        GPU_NAME=$(lspci | grep "VGA compatible controller: Intel" | head -1)
        echo "  OK GPU Intel: $GPU_NAME"
    else
        echo "  i  Nessuna GPU Intel rilevata via lspci"
    fi
fi

# ======================================================================
# FASE 7: Integrazione desktop
# ======================================================================

echo ""
echo "-- Integrazione desktop --"

# Crea file .desktop per l'utente
DESKTOP_FILE="$HOME/.local/share/applications/${APP_ID}.desktop"
mkdir -p "$(dirname "$DESKTOP_FILE")"
if [ -f "$SCRIPT_DIR/${APP_ID}.desktop" ]; then
    cp "$SCRIPT_DIR/${APP_ID}.desktop" "$DESKTOP_FILE"
    sed -i "s|Exec=glm-ocr|Exec=$VENV_DIR/bin/python $SCRIPT_DIR/main.py|" "$DESKTOP_FILE"
    echo "  OK File .desktop creato"
else
    # Crea file .desktop da zero
    cat > "$DESKTOP_FILE" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=Riconoscimento ottico con motore GLM-OCR (llama.cpp/SYCL/GGUF)
Exec=${VENV_DIR}/bin/python ${SCRIPT_DIR}/main.py
Icon=glm-ocr
Categories=Office;Graphics;
StartupNotify=true
DESKTOP_EOF
    echo "  OK File .desktop creato (generato)"
fi

# Copia icona
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
if [ -f "$SCRIPT_DIR/assets/icons/glm-ocr.svg" ]; then
    cp "$SCRIPT_DIR/assets/icons/glm-ocr.svg" "$ICON_DIR/"
    echo "  OK Icona copiata"
fi

# Aggiorna cache desktop
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

# ======================================================================
# RIEPILOGO
# ======================================================================

echo ""
echo "+==================================================+"
echo "|          Installazione completata!               |"
echo "+==================================================+"
echo ""
echo "  Avvia con:"
echo "    $VENV_DIR/bin/python $SCRIPT_DIR/main.py"
echo ""
echo "  Oppure cerca '${APP_NAME}' nel menu applicazioni."
echo ""
echo "  Backend: llama.cpp + SYCL (GPU Intel Arc)"
echo ""
echo "  Struttura self-contained:"
echo "    .venv/bin/llama-server  ← binary SYCL (pacman non lo tocca)"
echo "    .venv/lib/              ← librerie condivise (libggml-sycl.so, etc.)"
echo "    .cache/llama.cpp/       ← sorgenti (per ricompilazione futura)"
echo "    ~/.cache/glm-ocr/       ← modelli GGUF"
echo ""
echo "  Per aggiornare llama-server (dopo aggiornamento pacman):"
echo "    cd $SCRIPT_DIR/.cache/llama.cpp && git pull"
echo "    rm -rf build && mkdir build && cd build"
echo "    bash -c 'source /opt/intel/oneapi/setvars.sh && \\"
echo "      cmake .. -DGGML_SYCL=1 -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx && \\"
echo "      cmake --build . --config Release -j\$(nproc)'"
echo "    cp bin/llama-server $VENV_DIR/bin/llama-server"
echo "    cp bin/libggml-sycl.so* bin/libggml.so* bin/libggml-cpu.so* \\"
echo "       bin/libggml-base.so* bin/libllama.so* bin/libllama-common.so* \\"
echo "       bin/libllama-server-impl.so* bin/libmtmd.so* $VENV_DIR/lib/"
