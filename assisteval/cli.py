"""Komut satırı.

  python -m assisteval smoke                          # login + yeni sohbet + /get_started (bağlantı kontrolü)
  python -m assisteval smoke --mesaj "Kampanyalar"    # + tek mesaj
  python -m assisteval run scenarios/ornek            # klasördeki tüm senaryolar
  python -m assisteval run senaryo.yaml --assistant mock --llm mock
"""

import argparse
import contextlib
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .simulator.assistant_client import AssistantClient
from .config import ConfigError, Credentials, load_settings
from .simulator.llm import MockLLM, OpenAICompatibleLLM
from .simulator.mock_assistant import MockServer
from .simulator.runner import run_scenario
from .simulator.scenario import ScenarioError, load_scenario
from .simulator.user import LLMUser, ScriptUser

MOCK_CREDS = Credentials(
    customer_id="00000000", gsm_number="900000000000", password="121212", otp="121212",
    ext_u_name="mock", ext_u_password="mock", reg_ext_u_name="mock", reg_ext_u_password="mock", reg_user_id="mock",
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="assisteval", description="AssistEval: bankacılık asistanı test simülatörü")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--assistant", choices=("real", "mock"), default="real", help="gerçek asistan veya sahte sunucu")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser("smoke", help="bağlantı kontrolü: login + yeni sohbet + /get_started")
    smoke.add_argument("--mesaj", help="açılıştan sonra gönderilecek tek mesaj")

    run = sub.add_parser("run", help="senaryo(ları) koş")
    run.add_argument("paths", nargs="+", help="senaryo dosyaları veya klasörleri")
    run.add_argument("--llm", choices=("openai", "mock"), default="openai", help="yönlendirmeli mod için simülatör LLM'i")
    run.add_argument("--sessiz", action="store_true", help="sohbeti konsola yazdırma")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    try:
        settings = load_settings(args.config)
        with _client(settings, args.assistant) as client:
            if args.command == "smoke":
                return _smoke(client, args.mesaj)
            return _run(settings, client, args)
    except (ConfigError, ScenarioError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


@contextlib.contextmanager
def _client(settings, mode: str):
    if mode == "real":
        yield AssistantClient(settings.assistant, Credentials.from_env())
        return
    with MockServer() as srv:
        cfg = replace(settings.assistant, base_url=srv.base_url, chatbot_message_url=srv.chatbot_message_url)
        yield AssistantClient(cfg, MOCK_CREDS)


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
        user, llm_name = _user_for(s, settings, args.llm)
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


def _user_for(s, settings, llm_choice: str):
    if s.mod == "script":
        return ScriptUser(s), None
    llm = MockLLM(s.yonlendirme) if llm_choice == "mock" else OpenAICompatibleLLM(settings.llm)
    return LLMUser(s, llm), llm.name


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
