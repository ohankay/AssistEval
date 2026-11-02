"""Testler için sahte servisler: banka asistanı + simülatör ve hakem LLM'leri.

Ürün kodu bunları bilmez; testler ve CI, ürünün gerçek istemcilerini config.yaml'da bu sunucunun
adresleri yazılı olarak çalıştırır (point_workspace_to).

  /BOA.Integration.MobileBranch/...   Login → OTP → conversation akışı, token süresi
  /chatbot//api/Chat/Message          conversationId'ye bağlı sohbet bağlamı (metin, buton, kart)
  /simulator/v1/chat/completions      yönlendirme adımlarını sırayla oynayan simülatör LLM'i
  /judge/v1/chat/completions          her zaman geçen hakem
  /<rol>/v1/models                    model listesi (assisteval check --llm)

Asistanın cevap formatı gerçek format netleşene kadar tahminidir: metin, buton ve kart içeren JSON listesi.
"""

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import yaml

MAIN_MENU = [
    {"title": "Kampanyalar", "payload": "/kampanyalar"},
    {"title": "Para Transferi", "payload": "/para_transferi"},
]
RECIPIENTS = {"A1": "Ahmet Yılmaz", "A2": "Ayşe Demir"}


class FakeBank:
    def __init__(self, otp: str = "121212", token_ttl: float = 300):
        self.otp = otp
        self.token_ttl = token_ttl
        self.tokens: dict[str, float] = {}  # token → bitiş zamanı
        self.conversations: dict[str, dict] = {}  # conversationId → bağlam
        self.registered_devices: set[str] = set()
        self.login_count = 0

    # ------------------------------------------------------------- auth
    def _issue_token(self) -> str:
        token = uuid.uuid4().hex
        self.tokens[token] = time.monotonic() + self.token_ttl
        return token

    def token_valid(self, auth_header: str | None) -> bool:
        token = (auth_header or "").removeprefix("Bearer ").strip()
        return self.tokens.get(token, 0) > time.monotonic()

    def handle_service(self, method: str, body: dict, auth: str | None) -> tuple[int, dict]:
        if method == "LoginForMobileBranch":
            self.registered_devices.add(body.get("DeviceId"))
            return 200, {"Success": True, "SessionKey": uuid.uuid4().hex}
        if method == "InitialLogin":
            if body.get("DeviceId") not in self.registered_devices:
                return 200, {"Success": False, "Results": [{"ErrorMessage": "Cihaz kayıtlı değil"}]}
            self.login_count += 1
            return 200, {"Success": True, "SessionKey": uuid.uuid4().hex, "AuthenticationToken": self._issue_token()}
        if not self.token_valid(auth):
            return 401, {"Success": False, "Results": [{"ErrorMessage": "Yetkisiz"}]}
        if method == "SendSmsOtp":
            return 200, {"Success": True}
        if method == "OtpLoginCompleteNew":
            if body.get("GeneratedOtp") != self.otp:
                return 200, {"Success": False, "Results": [{"ErrorMessage": "OTP hatalı"}]}
            return 200, {"Success": True, "LoginResponse": {"AuthenticationToken": self._issue_token(), "SessionKey": uuid.uuid4().hex}}
        if method == "ChatBotInsertConversation":
            self.conversations[body["ConversationId"]] = {"state": None}
            return 200, {"Success": True, "Value": True}
        return 404, {"Success": False}

    # ------------------------------------------------------------- chat
    def handle_message(self, form: dict, auth: str | None) -> tuple[int, object]:
        if not self.token_valid(auth):
            return 401, {"error": "token geçersiz"}
        conv = self.conversations.get(form.get("conversationId"))
        if conv is None:
            return 400, {"error": "conversation bulunamadı"}
        return 200, self._bot(conv, form.get("text", ""))

    def _bot(self, conv: dict, text: str) -> list:
        t = text.casefold()
        state = conv["state"]

        if text == "/get_started":
            conv["state"] = None
            return [{"text": "Merhaba, ben dijital asistanınız. Size nasıl yardımcı olabilirim?", "buttons": MAIN_MENU}]

        if text.startswith("/kampanya_detay"):
            return [{"text": "Market alışverişlerinizde %10 kâr payı iadesi. Kampanya 31 Aralık'a kadar geçerlidir."}]
        if text == "/kampanyalar" or "kampanya" in t:
            return [
                {"text": "Size özel kampanyalar:"},
                {
                    "custom": {
                        "cards": [
                            {"title": "Market Kampanyası", "subtitle": "%10 kâr payı iadesi",
                             "buttons": [{"title": "Detay", "payload": '/kampanya_detay{"id":1}'}]},
                            {"title": "Akaryakıt Kampanyası", "subtitle": "500 TL'ye 50 TL puan",
                             "buttons": [{"title": "Detay", "payload": '/kampanya_detay{"id":2}'}]},
                        ]
                    }
                },
            ]

        if text == "/para_transferi" or any(w in t for w in ("para gönder", "eft", "havale", "transfer")):
            conv.update(state="alici")
            buttons = [{"title": n, "payload": f'/alici{{"id":"{k}"}}'} for k, n in RECIPIENTS.items()]
            return [{"text": "Kime para göndermek istiyorsunuz? Kayıtlı alıcılarınız:", "buttons": buttons}]

        if state == "alici":
            name = next((n for k, n in RECIPIENTS.items() if k in text or n.casefold() in t), None)
            if not name:
                return [{"text": "Bu isimde kayıtlı alıcı bulamadım. Lütfen listeden seçin."}]
            conv.update(state="tutar", alici=name)
            return [{"text": f"{name} adlı alıcıya ne kadar göndermek istiyorsunuz?"}]

        if state == "tutar":
            m = re.search(r"\d+", text.replace(".", ""))
            if not m:
                return [{"text": "Lütfen göndermek istediğiniz tutarı yazın."}]
            conv.update(state="onay", tutar=int(m.group()))
            return [{
                "text": f"{conv['alici']} adlı alıcıya {conv['tutar']} TL gönderilecek. Onaylıyor musunuz?",
                "buttons": [{"title": "Onayla", "payload": "/onayla"}, {"title": "Vazgeç", "payload": "/vazgec"}],
            }]

        if state == "onay":
            conv["state"] = None
            if text == "/onayla" or t.strip() in ("evet", "onaylıyorum"):
                return [{"text": "İşleminiz başarıyla gerçekleştirildi. Dekont numarası: 2026102900123"}]
            return [{"text": "İşleminiz iptal edildi."}]

        return [{"text": "Üzgünüm, bunu anlayamadım. Aşağıdakilerden birini seçebilirsiniz.", "buttons": MAIN_MENU}]


# ------------------------------------------------------------- sahte LLM'ler (OpenAI uyumlu)
QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
BUTTON_LINE = re.compile(r"^\s*\[(.+?)\] →", re.MULTILINE)
STEP_LINE = re.compile(r"^\d+\.\s+(.*)$")


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def guided_reply(messages: list[dict]) -> str:
    """Simülatör LLM'inin yerine: sistem prompt'undaki yönlendirme adımlarını sırayla oynar.

    Her turda sıradaki adımdaki "çift tırnaklı" ifadeyi söyler; ifade asistanın sunduğu bir
    butonun başlığıysa butona tıklar. Adımlar bitince BITTI der.
    """
    steps = _guidance_steps(messages[0]["content"] if messages and messages[0]["role"] == "system" else "")
    turn = sum(1 for m in messages if m["role"] == "assistant")
    if turn >= len(steps):
        return json.dumps({"durum": "BITTI", "aksiyon": "mesaj", "deger": "", "gerekce": "Yönlendirme adımları tamamlandı"})
    match = QUOTED.search(steps[turn])
    phrase = (match.group(1) or match.group(2)) if match else steps[turn]
    last_reply = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    buttons = {_norm(b): b for b in BUTTON_LINE.findall(last_reply)}
    if _norm(phrase) in buttons:
        decision = {"aksiyon": "buton", "deger": buttons[_norm(phrase)]}
    else:
        decision = {"aksiyon": "mesaj", "deger": phrase}
    return json.dumps({"durum": "DEVAM", **decision, "gerekce": f"Yönlendirme {turn + 1}. adım"}, ensure_ascii=False)


def _guidance_steps(system_prompt: str) -> list[str]:
    section = system_prompt.split("## Yönlendirme", 1)[-1].split("\n##", 1)[0] if "## Yönlendirme" in system_prompt else ""
    return [m.group(1) for line in section.splitlines() if (m := STEP_LINE.match(line.strip()))]


class GuidedFakeLLM:
    """LLMUser'a doğrudan verilebilen sahte simülatör LLM'i (HTTP'siz birim testleri için)."""

    name = "fake-simulator"

    def chat(self, messages: list[dict]) -> str:
        return guided_reply(messages)


JUDGE_VERDICT = json.dumps({"pass": True, "score": 1, "reason": "Sahte hakem: değerlendirme yapılmadı"}, ensure_ascii=False)
LLM_MODELS = {"simulator": "fake-simulator", "judge": "fake-judge"}


def _completion(model: str, content: str) -> dict:
    return {
        "id": "fake", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _make_handler(bank: FakeBank):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            role = self.path.strip("/").split("/", 1)[0]
            if role in LLM_MODELS and self.path.rstrip("/").endswith("/v1/models"):
                return self._send(200, {"object": "list", "data": [{"id": LLM_MODELS[role], "object": "model"}]})
            self._send(404, {"error": "yok"})

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
            auth = self.headers.get("Authorization")
            path = self.path.rstrip("/")
            if path == "/simulator/v1/chat/completions":
                body = json.loads(raw)
                return self._send(200, _completion(LLM_MODELS["simulator"], guided_reply(body["messages"])))
            if path == "/judge/v1/chat/completions":
                return self._send(200, _completion(LLM_MODELS["judge"], JUDGE_VERDICT))
            if path.endswith("/api/Chat/Message"):
                form = {k: v[0] for k, v in parse_qs(raw).items()}
                return self._send(*bank.handle_message(form, auth))
            self._send(*bank.handle_service(self.path.rsplit("/", 1)[-1], json.loads(raw or "{}"), auth))

        def _send(self, status: int, payload) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


class FakeServer:
    """Arka planda çalışan sahte sunucu; `with FakeServer() as srv:` ile kullanılır."""

    def __init__(self, bank: FakeBank | None = None, host: str = "127.0.0.1", port: int = 0):
        self.bank = bank or FakeBank()
        self.httpd = ThreadingHTTPServer((host, port), _make_handler(self.bank))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def root(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def base_url(self) -> str:
        return self.root + "/BOA.Integration.MobileBranch"

    @property
    def chatbot_message_url(self) -> str:
        return self.root + "/chatbot//api/Chat/Message"

    def llm_base_url(self, role: str) -> str:
        return f"{self.root}/{role}/v1"

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


FAKE_CREDS = {
    "CUSTOMER_ID": "00000000", "GSM_NUMBER": "900000000000", "PASSWORD": "121212", "OTP": "121212",
    "EXT_U_NAME": "test", "EXT_U_PASSWORD": "test", "REG_EXT_U_NAME": "test", "REG_EXT_U_PASSWORD": "test",
    "REG_USER_ID": "test",
}


def point_workspace_to(folder: Path, srv: FakeServer) -> None:
    """`assisteval init` ile oluşmuş çalışma klasörünü sahte sunucuya yönlendirir:
    config.yaml'daki asistan ve iki LLM adresi + .env'deki test kimlik bilgileri."""
    path = Path(folder) / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["assistant"].update(base_url=srv.base_url, chatbot_message_url=srv.chatbot_message_url)
    for role, model in LLM_MODELS.items():
        data[role] = {**(data.get(role) or {}), "base_url": srv.llm_base_url(role), "model": model}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (Path(folder) / ".env").write_text("".join(f"{k}={v}\n" for k, v in FAKE_CREDS.items()), encoding="utf-8")


if __name__ == "__main__":
    # CI: kurulu paketi ağ kapalıyken uçtan uca denemek için.
    #   python tests/fakes.py <çalışma klasörü>
    # Klasörü sahte sunucuya yönlendirir, hazır olunca <klasör>/.fake-ready yazar ve kapatılana kadar çalışır.
    import sys

    workspace = Path(sys.argv[1])
    with FakeServer() as server:
        point_workspace_to(workspace, server)
        (workspace / ".fake-ready").write_text(server.root, encoding="utf-8")
        print(f"Sahte sunucu: {server.root}", flush=True)
        server.thread.join()
