"""Offline Windows kurulum paketlerini üretir:

    release/assisteval-windows-x64.zip   (64-bit Python)
    release/assisteval-windows-x86.zip   (32-bit Python)

    pip install uv packaging && python scripts/build_bundle.py [x64|x86]

Her zip; assisteval wheel'ini, o mimari ve CPython 3.10-3.14 için tüm bağımlılık wheel'lerini
(internet olmadan kurulum için), install.cmd'yi ve kurulum rehberini içerir.
"""

from __future__ import annotations

import base64
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
TOP = "assisteval"

# Her pakette mutlaka bulunması gerekenler
REQUIRED = ("assisteval", "requests", "urllib3", "certifi", "idna", "charset-normalizer", "pyyaml",
            "python-dotenv", "truststore")

# C eklentisi opsiyonel olan paketler. Bazı mimari/sürümlerde hazır wheel'leri yok (örn. PyYAML'ın
# win32 + Python 3.14 wheel'i yok). Bunlar için C eklentisi çıkarılmış saf Python wheel'i (py3-none-any)
# de pakete eklenir: pip platforma özel wheel varsa onu tercih eder, yoksa saf Python'a düşer.
PURE_FALLBACK = ("pyyaml",)

# mimari -> (uv hedef üçlüsü, pip platform etiketi)
ARCHES = {
    "x64": ("x86_64-pc-windows-msvc", "win_amd64"),
    "x86": ("i686-pc-windows-msvc", "win32"),
}


def _windows_requirements(arch: str, version: str, out: Path, find_links: Path | None = None) -> Path:
    """Bağımlılık ağacını, bu mimari ve Python sürümü için WINDOWS'ta çözülmüş haliyle sabitler.

    pip, ``sys_platform == "win32"`` gibi işaretleri build makinesine göre değerlendirir; uv ise
    hedef platforma göre çözer. ``--only-binary`` hedef için wheel yayınlamış sürümlerle sınırlar.
    """
    triple, _ = ARCHES[arch]
    req = out / f"requirements-{arch}-{version}.txt"
    subprocess.run(
        ["uv", "pip", "compile", str(ROOT / "pyproject.toml"), "--python-platform", triple,
         "--python-version", version, "--only-binary", ":all:", "--no-header", "--no-annotate",
         "-q", "-o", str(req)] + (["--find-links", str(find_links)] if find_links else []),
        check=True,
    )
    return req


def _pins(req: Path) -> dict[str, str]:
    pins = {}
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.split(";")[0].split("#")[0].strip()
        if "==" in line:
            name, ver = line.split("==", 1)
            pins[canonicalize_name(name.split("[")[0])] = ver.strip()
    return pins


def _pure_wheels(dest: Path, tmp: Path) -> None:
    """PURE_FALLBACK paketlerinin, C eklentisi çıkarılmış py3-none-any wheel'lerini üretir."""
    pins = _pins(_windows_requirements("x64", "3.13", tmp))  # sürüm, diğer wheel'lerle aynı olsun
    for name in PURE_FALLBACK:
        src = tmp / f"pure-src-{name}"
        _pip("download", f"{name}=={pins[name]}", "--no-deps", "--only-binary=:all:", "--platform", "win_amd64",
             "--python-version", "3.13", "-d", str(src))
        _strip_to_pure(next(src.glob("*.whl")), dest)


def _strip_to_pure(whl: Path, dest: Path) -> Path:
    name, ver, _, _ = parse_wheel_filename(whl.name)
    dist = whl.name.split("-")[0]
    out = dest / f"{dist}-{ver}-py3-none-any.whl"
    records = []
    with zipfile.ZipFile(whl) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        dist_info = next(n.split("/")[0] for n in zin.namelist() if n.split("/")[0].endswith(".dist-info"))
        for item in zin.infolist():
            if item.filename.endswith((".pyd", ".so")) or item.filename == f"{dist_info}/RECORD":
                continue
            data = zin.read(item)
            if item.filename == f"{dist_info}/WHEEL":
                # WHEEL e-posta başlığı formatında: boş satır başlıkları bitirir, o yüzden boş satırlar da atılır
                lines = [ln for ln in data.decode().splitlines()
                         if ln.strip() and not ln.startswith(("Tag:", "Root-Is-Purelib:"))]
                data = ("\n".join(lines + ["Root-Is-Purelib: true", "Tag: py3-none-any"]) + "\n").encode()
            zout.writestr(item.filename, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            records.append(f"{item.filename},sha256={digest},{len(data)}")
        records.append(f"{dist_info}/RECORD,,")
        zout.writestr(f"{dist_info}/RECORD", "\n".join(records) + "\n")
    return out


def _verify(wheelhouse: Path, req: Path, arch: str, version: str) -> None:
    """Sabitlenen her paketin bu Python sürümü + mimaride kurulabilir bir wheel'i olmalı.

    Sessizce atlanmaz: eksik paket ve gereken wheel etiketi açıkça raporlanır.
    """
    _, platform_tag = ARCHES[arch]
    py = tuple(int(x) for x in version.split("."))
    target = set(cpython_tags(py, platforms=[platform_tag])) | set(compatible_tags(py, platforms=[platform_tag]))
    have: dict[str, set[str]] = {}
    for whl in wheelhouse.glob("*.whl"):
        name, ver, _, tags = parse_wheel_filename(whl.name)
        if tags & target:
            have.setdefault(canonicalize_name(name), set()).add(str(ver))
    pins = _pins(req)
    missing = [f"{n}=={v}" for n, v in pins.items() if v not in have.get(n, set())]
    missing += [n for n in REQUIRED if canonicalize_name(n) not in have]
    if missing:
        tag = f"cp{py[0]}{py[1]}-cp{py[0]}{py[1]}-{platform_tag} (veya py3-none-any / abi3)"
        raise SystemExit(f"[{arch} / Python {version}] uyumlu wheel yok: {', '.join(missing)} - gereken etiket: {tag}")


def _pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args, "--disable-pip-version-check", "-q"], check=True)


def build(arch: str) -> Path:
    _, platform_tag = ARCHES[arch]
    out = ROOT / "release" / f"assisteval-windows-{arch}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        wheelhouse = Path(tmp) / "wheelhouse"
        wheelhouse.mkdir()
        _pip("wheel", str(ROOT), "--no-deps", "-w", str(wheelhouse))
        pure = Path(tmp) / "pure"
        pure.mkdir()
        _pure_wheels(pure, Path(tmp))
        for version in PYTHON_VERSIONS:
            req = _windows_requirements(arch, version, Path(tmp), find_links=pure)
            _pip("download", "-r", str(req), "--no-deps", "--platform", platform_tag, "--python-version",
                 version, "--only-binary=:all:", "--find-links", str(pure), "-d", str(wheelhouse))
        for whl in pure.glob("*.whl"):  # platform wheel'i olan sürümlerde bile yedek olarak dursun
            (wheelhouse / whl.name).write_bytes(whl.read_bytes())
        for version in PYTHON_VERSIONS:
            _verify(wheelhouse, Path(tmp) / f"requirements-{arch}-{version}.txt", arch, version)

        out.parent.mkdir(exist_ok=True)
        if out.exists():
            out.unlink()
        files: list[tuple[Path, str]] = [
            (ROOT / "bundle" / "KURULUM_REHBERI.md", "KURULUM_REHBERI.md"),
            (ROOT / "bundle" / "install.cmd", "install.cmd"),
            (ROOT / "README.md", "README.md"),
        ]
        files += [(p, f"wheelhouse/{p.name}") for p in sorted(wheelhouse.iterdir())]
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{TOP}/bundle_arch.txt", arch)  # install.cmd tarafından okunur
            for src, arc in files:
                zf.write(src, f"{TOP}/{arc}")
    return out


if __name__ == "__main__":
    for name in sys.argv[1:] or list(ARCHES):
        if name not in ARCHES:
            sys.exit(f"bilinmeyen mimari {name!r}; şunlardan biri olmalı: {', '.join(ARCHES)}")
        path = build(name)
        print(f"{path} ({path.stat().st_size / 1_048_576:.1f} MB)")
