"""Offline Windows x64 kurulum paketini üretir:

    release/assisteval-windows-x64.zip

    pip install uv packaging && python scripts/build_bundle.py      (npm ve internet gerekir)

Zip içeriği (hedef makinede internet gerekmez):
  wheelhouse/   assisteval wheel'i + CPython 3.10-3.14 / win_amd64 için tüm bağımlılık wheel'leri
  node/         taşınabilir Node.js (node.exe), promptfoo'yu çalıştırmak için
  promptfoo/    promptfoo ve bağımlılıkları (node_modules), Windows x64 ikilileriyle
  install.cmd, KURULUM_REHBERI.md, README.md
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
TOP = "assisteval"
UV_TARGET, PLATFORM_TAG = "x86_64-pc-windows-msvc", "win_amd64"

NODE_VERSION = "22.23.3"  # LTS; promptfoo en az 22.22 istiyor
PROMPTFOO_VERSION = "0.125.1"

# Her pakette mutlaka bulunması gerekenler
REQUIRED = ("assisteval", "requests", "urllib3", "certifi", "idna", "charset-normalizer", "pyyaml",
            "python-dotenv", "truststore")

# promptfoo'nun opsiyonel sağlayıcıları (Azure, AWS, PDF, Redis...) pakete alınmaz. Çalışma için gereken
# platforma özel ikililer: paket -> Windows x64 ikili paketi (sürüm, paketin optionalDependencies'inden)
NATIVE = {"libsql": "@libsql/win32-x64-msvc", "esbuild": "@esbuild/win32-x64"}
# Çalışma anında kullanılmayan dosyalar (boyutu ~yarıya indirir)
PRUNE_SUFFIXES = (".map", ".d.ts", ".d.mts", ".d.cts", ".md")


def _windows_requirements(version: str, out: Path) -> Path:
    """Bağımlılık ağacını, bu Python sürümü için WINDOWS x64'te çözülmüş haliyle sabitler.

    pip, ``sys_platform == "win32"`` gibi işaretleri build makinesine göre değerlendirir; uv ise
    hedef platforma göre çözer. ``--only-binary`` hedef için wheel yayınlamış sürümlerle sınırlar.
    """
    req = out / f"requirements-{version}.txt"
    subprocess.run(
        ["uv", "pip", "compile", str(ROOT / "pyproject.toml"), "--python-platform", UV_TARGET,
         "--python-version", version, "--only-binary", ":all:", "--no-header", "--no-annotate",
         "-q", "-o", str(req)],
        check=True,
    )
    return req


def _verify(wheelhouse: Path, req: Path, version: str) -> None:
    """Sabitlenen her paketin bu Python sürümünde kurulabilir bir wheel'i olmalı.

    Sessizce atlanmaz: eksik paket ve gereken wheel etiketi açıkça raporlanır.
    """
    py = tuple(int(x) for x in version.split("."))
    target = set(cpython_tags(py, platforms=[PLATFORM_TAG])) | set(compatible_tags(py, platforms=[PLATFORM_TAG]))
    have: dict[str, set[str]] = {}
    for whl in wheelhouse.glob("*.whl"):
        name, ver, _, tags = parse_wheel_filename(whl.name)
        if tags & target:
            have.setdefault(canonicalize_name(name), set()).add(str(ver))
    pins = {}
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.split(";")[0].split("#")[0].strip()
        if "==" in line:
            name, ver = line.split("==", 1)
            pins[canonicalize_name(name.split("[")[0])] = ver.strip()
    missing = [f"{n}=={v}" for n, v in pins.items() if v not in have.get(n, set())]
    missing += [n for n in REQUIRED if canonicalize_name(n) not in have]
    if missing:
        tag = f"cp{py[0]}{py[1]}-cp{py[0]}{py[1]}-{PLATFORM_TAG} (veya py3-none-any / abi3)"
        raise SystemExit(f"[Python {version}] uyumlu wheel yok: {', '.join(missing)} - gereken etiket: {tag}")


def _pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args, "--disable-pip-version-check", "-q"], check=True)


def _wheelhouse(dest: Path, tmp: Path) -> None:
    _pip("wheel", str(ROOT), "--no-deps", "-w", str(dest))
    for version in PYTHON_VERSIONS:
        req = _windows_requirements(version, tmp)
        _pip("download", "-r", str(req), "--no-deps", "--platform", PLATFORM_TAG, "--python-version",
             version, "--only-binary=:all:", "-d", str(dest))
    for version in PYTHON_VERSIONS:
        _verify(dest, tmp / f"requirements-{version}.txt", version)


def _node(dest: Path) -> None:
    """nodejs.org'dan Windows x64 Node.js'i indirir, SHA256'yı doğrular, node.exe + LICENSE'ı çıkarır."""
    base = f"https://nodejs.org/dist/v{NODE_VERSION}/"
    name = f"node-v{NODE_VERSION}-win-x64.zip"
    sums = urllib.request.urlopen(base + "SHASUMS256.txt", timeout=60).read().decode()
    expected = next(line.split()[0] for line in sums.splitlines() if line.endswith(" " + name))
    data = urllib.request.urlopen(base + name, timeout=600).read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"{name}: SHA256 uyuşmuyor")
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in ("node.exe", "LICENSE"):
            (dest / member).write_bytes(zf.read(f"node-v{NODE_VERSION}-win-x64/{member}"))


def _promptfoo(dest: Path) -> None:
    """promptfoo'yu Windows x64 için (opsiyonel sağlayıcılar olmadan) kurar ve budar."""
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm bulunamadı (Node.js 22+ kurun)")
    dest.mkdir(parents=True)
    (dest / "package.json").write_text(json.dumps({"name": "assisteval-promptfoo", "private": True}), encoding="utf-8")
    flags = ["--os=win32", "--cpu=x64", "--omit=dev", "--omit=optional", "--omit=peer", "--ignore-scripts",
             "--no-audit", "--no-fund", "--no-package-lock", "--loglevel=error"]
    subprocess.run([npm, "install", f"promptfoo@{PROMPTFOO_VERSION}", *flags], cwd=dest, check=True)
    modules = dest / "node_modules"
    natives = []
    for pkg, native in NATIVE.items():
        meta = json.loads((modules / pkg / "package.json").read_text(encoding="utf-8"))
        natives.append(f"{native}@{meta['optionalDependencies'][native]}")
    # Doğrudan istenen paketlerde --os/--cpu dikkate alınmaz (EBADPLATFORM): --force platform kontrolünü atlar
    subprocess.run([npm, "install", "--no-save", "--force", *natives, *flags], cwd=dest, check=True)
    for native in NATIVE.values():
        if not (modules / native / "package.json").exists():
            raise SystemExit(f"{native} kurulamadı")
    for path in modules.rglob("*"):
        if path.is_file() and path.name.endswith(PRUNE_SUFFIXES) and not path.name.upper().startswith(("LICENSE", "LICENCE")):
            path.unlink()
    installed = json.loads((modules / "promptfoo" / "package.json").read_text(encoding="utf-8"))["version"]
    if installed != PROMPTFOO_VERSION:
        raise SystemExit(f"promptfoo {installed} kuruldu, beklenen {PROMPTFOO_VERSION}")


def build() -> Path:
    out = ROOT / "release" / "assisteval-windows-x64.zip"
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        wheelhouse = tmp / "wheelhouse"
        wheelhouse.mkdir()
        _wheelhouse(wheelhouse, tmp)
        _node(tmp / "node")
        _promptfoo(tmp / "promptfoo")

        out.parent.mkdir(exist_ok=True)
        if out.exists():
            out.unlink()
        files: list[tuple[Path, str]] = [
            (ROOT / "bundle" / "KURULUM_REHBERI.md", "KURULUM_REHBERI.md"),
            (ROOT / "bundle" / "install.cmd", "install.cmd"),
            (ROOT / "README.md", "README.md"),
        ]
        for folder in ("wheelhouse", "node", "promptfoo"):
            files += [(p, p.relative_to(tmp).as_posix()) for p in sorted((tmp / folder).rglob("*")) if p.is_file()]
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{TOP}/bundle_arch.txt", "x64")  # install.cmd tarafından okunur
            zf.writestr(f"{TOP}/versions.txt", f"node={NODE_VERSION}\npromptfoo={PROMPTFOO_VERSION}\n")
            for src, arc in files:
                zf.write(src, f"{TOP}/{arc}")
    return out


if __name__ == "__main__":
    path = build()
    print(f"{path} ({path.stat().st_size / 1_048_576:.1f} MB)")
