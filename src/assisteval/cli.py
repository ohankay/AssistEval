"""Komut satırı.

  assisteval init calisma                     # çalışma klasörü: config.yaml, .env, örnek senaryolar
  assisteval check                            # kurulum + ayar kontrolü (ağ gerektirmez)
  assisteval smoke                            # login + yeni sohbet + /get_started (bağlantı kontrolü)
  assisteval smoke --mesaj "Kampanyalar"      # + tek mesaj
  assisteval run scenarios/ornek              # klasördeki tüm senaryolar
  assisteval --assistant mock run scenarios/ornek --llm mock   # tamamen offline deneme
  assisteval eval scenarios/ornek             # promptfoo ile koşum + değerlendirme + HTML rapor
  assisteval --assistant mock eval scenarios/ornek --llm mock --judge mock     # tamamen offline
  assisteval promptfoo view                   # promptfoo arayüzü (koşum geçmişi)
"""

import argparse
import contextlib
import json
import logging
import os
import platform
import shutil
import struct
import subprocess
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .config import ConfigError, Credentials, load_settings
from .evaluation import promptfoo as pf
from .runtime import assistant_client, simulated_user
from .simulator.assistant_client import AssistantClient
from .simulator.runner import run_scenario
from .simulator.scenario import ScenarioError, load_scenario


def main(argv=None) -> int:
    _setup_console()
    parser = argparse.ArgumentParser(prog="assisteval", description="AssistEval: bankacılık asistanı test simülatörü")
    parser.add_argument("--version", action="version", version=f"assisteval {__version__}")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--assistant", choices=("real", "mock"), default="real", help="gerçek asistan veya sahte sunucu")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="çalışma klasörü oluştur (config.yaml, .env, örnek senaryolar)")
    init.add_argument("folder", nargs="?", default=".")

    sub.add_parser("check", help="kurulum ve ayar kontrolü (ağ gerektirmez)")

    smoke = sub.add_parser("smoke", help="bağlantı kontrolü: login + yeni sohbet + /get_started")
    smoke.add_argument("--mesaj", help="açılıştan sonra gönderilecek tek mesaj")

    run = sub.add_parser("run", help="senaryo(ları) koş")
    run.add_argument("paths", nargs="+", help="senaryo dosyaları veya klasörleri")
    run.add_argument("--llm", choices=("openai", "mock"), default="openai", help="yönlendirmeli mod için simülatör LLM'i")
    run.add_argument("--sessiz", action="store_true", help="sohbeti konsola yazdırma")

    ev = sub.add_parser("eval", help="senaryoları promptfoo ile koş ve değerlendir")
    ev.add_argument("paths", nargs="+", help="senaryo dosyaları veya klasörleri")
    ev.add_argument("--llm", choices=("openai", "mock"), default="openai", help="yönlendirmeli mod için simülatör LLM'i")
    ev.add_argument("--judge", choices=("config", "mock"), default="config",
                    help="llm-rubric hakemi: config.yaml'daki judge/llm veya her zaman geçen sahte hakem")
    ev.add_argument("--etiket", action="append", default=[], help="sadece bu etiketteki senaryolar (tekrarlanabilir)")

    # "promptfoo" sonrası her şey olduğu gibi promptfoo'ya gider. argparse'a verilmez: REMAINDER,
    # "-" ile başlayan ilk argümanı (ör. --version) yakalamıyor.
    sub.add_parser("promptfoo", help="paketle gelen promptfoo'yu doğrudan çalıştır (ör. view, --version)")
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    if "promptfoo" in argv:
        i = argv.index("promptfoo")
        argv, passthrough = argv[: i + 1], argv[i + 1 :]

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.command == "init":
        return _init(Path(args.folder))
    if args.command == "check":
        return _check(args.config)
    if args.command == "promptfoo":
        return _promptfoo_passthrough(args.config, passthrough)
    try:
        settings = load_settings(args.config)
        if args.command == "eval":
            return _eval(settings, args)
        with assistant_client(settings, args.assistant) as client:
            if args.command == "smoke":
                return _smoke(client, args.mesaj)
            return _run(settings, client, args)
    except (ConfigError, ScenarioError, pf.PromptfooError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


def _setup_console() -> None:
    # Windows'ta çıktı dosyaya/pipe'a yönlendirilince yerel kod sayfası (cp1252/cp1254) kullanılır ve
    # Türkçe karakterler kaybolur: yönlendirilmiş çıktı UTF-8 yazılsın. Konsolda Python zaten Unicode yazar;
    # yine de kodlanamayan bir sembol hata yerine '?' olsun.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
    # Kurumsal CA'lar Windows sertifika deposunda: requests da o depoyu kullansın.
    if os.environ.get("ASSISTEVAL_NO_TRUSTSTORE") != "1":
        with contextlib.suppress(Exception):
            import truststore

            truststore.inject_into_ssl()


def _init(folder: Path) -> int:
    templates = resources.files("assisteval") / "templates"
    folder.mkdir(parents=True, exist_ok=True)
    plan = [("config.yaml", "config.yaml"), ("env.example", ".env.example"), ("env.example", ".env")]
    for src, dst in plan:
        target = folder / dst
        if target.exists():
            print(f"  atlandı (zaten var): {target}")
            continue
        target.write_text((templates / src).read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  oluşturuldu: {target}")
    scenarios = folder / "scenarios" / "ornek"
    if scenarios.exists():
        print(f"  atlandı (zaten var): {scenarios}")
    else:
        with resources.as_file(templates / "scenarios" / "ornek") as src_dir:
            shutil.copytree(src_dir, scenarios)
        print(f"  oluşturuldu: {scenarios}")
    print(f"\nSonraki adım: {folder / '.env'} dosyasını doldurun, sonra bu klasörde 'assisteval check' çalıştırın.")
    return 0


def _check(config_path: str) -> int:
    report: dict = {
        "version": __version__,
        "python": platform.python_version(),
        "bits": struct.calcsize("P") * 8,
        "platform": platform.platform(),
    }
    ok = True
    try:
        settings = load_settings(config_path)
        report["config"] = str(Path(config_path).resolve())
        report["assistant_url"] = settings.assistant.chatbot_message_url
        report["llm"] = {"base_url": settings.llm.base_url, "model": settings.llm.model}
        report["output_dir"] = str(settings.output_dir)
        try:
            Credentials.from_env()
            report["env"] = "tamam"
        except ConfigError as e:
            report["env"] = str(e)
            ok = False
    except Exception as e:  # noqa: BLE001
        report["config_error"] = str(e)
        ok = False
    try:
        cmd = pf.find_promptfoo()
        out = subprocess.run(cmd + ["--version"], env=pf.promptfoo_env(None), capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=120)
        report["promptfoo"] = {"komut": cmd, "surum": out.stdout.strip().splitlines()[-1] if out.stdout.strip() else None}
        ok = ok and out.returncode == 0
    except Exception as e:  # noqa: BLE001
        report["promptfoo"] = {"hata": str(e)}
        ok = False
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


def _promptfoo_passthrough(config_path: str, args: list[str]) -> int:
    try:
        settings = load_settings(config_path)
    except ConfigError:
        settings = None  # config olmadan da çalışsın (ör. --version)
    try:
        return pf.run_promptfoo(args, settings)
    except pf.PromptfooError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


def _eval(settings, args) -> int:
    scenarios = [load_scenario(p) for p in _expand(args.paths)]
    if args.etiket:
        scenarios = [s for s in scenarios if set(args.etiket) & set(s.etiketler)]
    if not scenarios:
        print("Senaryo bulunamadı", file=sys.stderr)
        return 2
    pf.find_promptfoo()  # promptfoo yoksa koşuma başlamadan söyle
    if args.assistant == "real":
        Credentials.from_env()  # .env eksikse her senaryoda ayrı ayrı değil, baştan bir kez söyle

    with contextlib.ExitStack() as stack:
        judge_url = None
        if args.judge == "mock":
            from .simulator.mock_assistant import MockServer

            judge_url = stack.enter_context(MockServer()).openai_base_url
        run_dir = pf.prepare_run(scenarios, settings, args.assistant, args.llm, judge_url)
        print(f"Koşum klasörü: {run_dir}\n{len(scenarios)} senaryo promptfoo ile koşuluyor...\n")
        pf.run_promptfoo(["eval", "-c", "promptfooconfig.yaml", "--no-cache", "-j", "1",
                          "-o", "sonuclar.json", "rapor.html"], settings, cwd=run_dir)

    results = run_dir / "sonuclar.json"
    if not results.exists():
        print(f"HATA: promptfoo sonuç üretmedi ({results})", file=sys.stderr)
        return 2
    rows = pf.summarize(results)
    print("\n=== Değerlendirme ===")
    for r in rows:
        skor = f"{r['skor']:.2f}" if isinstance(r["skor"], (int, float)) else "-"
        metrikler = " ".join(f"{k}={v:.2f}" for k, v in r["metrikler"].items())
        print(f"{r['durum']:<6} {skor:>5}  {r['senaryo']}  {metrikler}")
        for k in r["kalanlar"]:
            print(f"         ✗ {k}")
    gecen = sum(r["durum"] == "GEÇTİ" for r in rows)
    print(f"\n{gecen}/{len(rows)} senaryo geçti")
    print(f"Rapor: {run_dir / 'rapor.html'}\nAyrıntılar: {results}")
    return 0 if gecen == len(rows) else 1


def _smoke(client: AssistantClient, mesaj: str | None) -> int:
    client.login()
    print("✓ Login tamam")
    conv = client.new_conversation()
    print(f"✓ Yeni sohbet: {conv.id}")
    for text in ["/get_started"] + ([mesaj] if mesaj else []):
        print(f"\n> {text}")
        print(conv.send(text).render())
    return 0


def _run(settings, client: AssistantClient, args) -> int:
    scenarios = [load_scenario(p) for p in _expand(args.paths)]
    if not scenarios:
        print("Senaryo bulunamadı", file=sys.stderr)
        return 2

    results = []
    for s in scenarios:
        print(f"\n=== {s.id} · {s.baslik} ({s.mod}) ===")
        user, llm_name = simulated_user(s, settings, args.llm)
        meta = {"asistan": args.assistant, "asistan_url": client.cfg.chatbot_message_url, "simulator_llm": llm_name}
        on_event = None if args.sessiz else _print_event
        transcript = run_scenario(s, client, user, meta, on_event)
        path = transcript.save(settings.output_dir)
        sonuc = transcript.data["sonuc"]
        print(f"--> {sonuc['durum']} ({sonuc['tur_sayisi']} tur): {sonuc['gerekce']}\n    {path}")
        results.append((s.id, sonuc))

    print("\n=== Özet ===")
    for sid, sonuc in results:
        print(f"{sid:<20} {sonuc['durum']:<18} {sonuc['tur_sayisi']} tur")
    return 0


def _expand(paths: list[str]) -> list[Path]:
    out = []
    for p in map(Path, paths):
        out += sorted(p.rglob("*.yaml")) if p.is_dir() else [p]
    return out


def _print_event(rol: str, text: str) -> None:
    prefix = "MÜŞTERİ " if rol == "musteri" else "ASİSTAN "
    lines = text.splitlines() or [""]
    print(prefix + lines[0])
    for line in lines[1:]:
        print(" " * len(prefix) + line)
