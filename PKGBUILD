# Maintainer: GLM OCR Team
pkgname=glm-ocr
pkgver=1.0.0
pkgrel=1
pkgdesc="OCR con motore GLM-OCR (llama.cpp + SYCL per GPU Intel Arc)"
arch=('x86_64')
url="https://github.com/glm-ocr/glm-ocr"
license=('MIT')
depends=(
    'python'
    'python-pyside6'
    'python-pillow'
    'python-numpy'
    'python-pymupdf'
    'python-huggingface-hub'
    'llama.cpp'
)
makedepends=('git' 'cmake' 'gcc')
optdepends=(
    'intel-oneapi-basekit: compilazione llama.cpp con SYCL (GPU Intel Arc)'
    'level-zero-loader: runtime SYCL'
    'level-zero-headers: header Level Zero'
    'intel-compute-runtime: runtime Intel GPU'
)
source=("git+https://github.com/glm-ocr/glm-ocr.git")
sha256sums=('SKIP')

package() {
    install -dm755 "$pkgdir/opt/glm-ocr"
    cp -r "$srcdir/$pkgname"/* "$pkgdir/opt/glm-ocr/"

    install -dm755 "$pkgdir/usr/bin"
    printf '#!/bin/bash\n/opt/glm-ocr/.venv/bin/python /opt/glm-ocr/main.py "$@"\n' \
        > "$pkgdir/usr/bin/glm-ocr"
    chmod 755 "$pkgdir/usr/bin/glm-ocr"

    install -Dm644 "$srcdir/$pkgname/com.glm-ocr.app.desktop" \
        "$pkgdir/usr/share/applications/com.glm-ocr.app.desktop" 2>/dev/null || true
}
