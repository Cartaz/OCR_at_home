# Maintainer: Cartaz
pkgname=glm-ocr
pkgver=1.0.0
pkgrel=2
pkgdesc="OCR locale con GLM-OCR e llama.cpp"
arch=('x86_64')
url="https://github.com/Cartaz/OCR_at_home"
license=('MIT')
depends=(
    'python'
    'pyside6'
    'python-pillow'
    'python-numpy'
    'python-pymupdf'
    'python-huggingface-hub'
    'llama-cpp'
)
makedepends=('git')
optdepends=(
    'ggml-sycl: backend SYCL per GPU Intel (sostituisce ggml generico)'
    'ggml-vulkan: backend Vulkan per GPU compatibili'
)
source=("$pkgname::git+https://github.com/Cartaz/OCR_at_home.git")
sha256sums=('SKIP')

package() {
    local appdir="$pkgdir/usr/share/glm-ocr"
    install -dm755 "$appdir"

    cp -a \
        "$srcdir/$pkgname/assets" \
        "$srcdir/$pkgname/config" \
        "$srcdir/$pkgname/core" \
        "$srcdir/$pkgname/qml" \
        "$srcdir/$pkgname/ui" \
        "$appdir/"
    install -Dm644 "$srcdir/$pkgname/main.py" "$appdir/main.py"

    install -dm755 "$pkgdir/usr/bin"
    cat > "$pkgdir/usr/bin/glm-ocr" <<'EOF'
#!/bin/sh
exec /usr/bin/python /usr/share/glm-ocr/main.py "$@"
EOF
    chmod 755 "$pkgdir/usr/bin/glm-ocr"

    install -Dm644 \
        "$srcdir/$pkgname/assets/icons/glm-ocr.svg" \
        "$pkgdir/usr/share/icons/hicolor/scalable/apps/glm-ocr.svg"

    install -dm755 "$pkgdir/usr/share/applications"
    cat > "$pkgdir/usr/share/applications/com.glm-ocr.app.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=GLM OCR
Comment=Riconoscimento ottico locale con GLM-OCR e llama.cpp
Exec=glm-ocr
Icon=glm-ocr
Terminal=false
Categories=Office;Graphics;
StartupNotify=true
EOF
}
