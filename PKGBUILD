# Maintainer: Cartaz
pkgname=glm-ocr
# Built from the git checkout: pkgver() derives the version from history.
# Unlike install.sh (which pins and compiles llama.cpp), this package uses the
# distribution's llama-cpp + ggml-sycl build.
pkgver=1.1.0
pkgrel=1
pkgdesc="OCR locale con GLM-OCR e llama.cpp SYCL"
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
    'ggml-sycl'
)
makedepends=('git')
source=("$pkgname::git+https://github.com/Cartaz/OCR_at_home.git")
sha256sums=('SKIP')

pkgver() {
    cd "$srcdir/$pkgname"
    printf "1.1.0.r%s.g%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
    local appdir="$pkgdir/usr/share/glm-ocr"
    install -dm755 "$appdir"

    cp -a \
        "$srcdir/$pkgname/assets" \
        "$srcdir/$pkgname/config" \
        "$srcdir/$pkgname/core" \
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
Comment=Riconoscimento ottico locale con GLM-OCR e llama.cpp SYCL
Exec=glm-ocr
Icon=glm-ocr
Terminal=false
Categories=Office;Graphics;
StartupNotify=true
EOF
}
