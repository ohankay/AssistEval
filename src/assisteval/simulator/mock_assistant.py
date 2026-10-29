"""Gerçek servislerle aynı endpoint'leri taklit eden sahte asistan sunucusu.

Login → OTP → conversation → message akışını, token süresini ve conversationId'ye
bağlı sohbet bağlamını taklit eder. Gerçek asistana erişim yokken simülatörü
uçtan uca denemek ve otomatik testler için kullanılır.

Cevap formatı (gerçek format netleşene kadar tahmini): metin, buton ve kart içeren JSON listesi.
"""

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

MAIN_MENU = [
    {"title": "Kampanyalar", "payload": "/kampanyalar"},
    {"title": "Para Transferi", "payload": "/para_transferi"},
]
RECIPIENTS = {"A1": "Ahmet Yılmaz", "A2": "Ayşe Demir"}


class MockBank:
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


def _make_handler(bank: MockBank):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
            auth = self.headers.get("Authorization")
            if self.path.rstrip("/").endswith("/api/Chat/Message"):
                form = {k: v[0] for k, v in parse_qs(raw).items()}
                status, payload = bank.handle_message(form, auth)
            else:
                status, payload = bank.handle_service(self.path.rsplit("/", 1)[-1], json.loads(raw or "{}"), auth)
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


class MockServer:
    """Arka planda çalışan sahte sunucu; `with MockServer() as srv:` ile kullanılır."""

    def __init__(self, bank: MockBank | None = None, host: str = "127.0.0.1", port: int = 0):
        self.bank = bank or MockBank()
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

    def __enter__(self) -> "MockServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
