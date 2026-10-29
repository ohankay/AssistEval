"""Bankacılık asistanına mobil bankacılık servisleri üzerinden bağlanan istemci.

Akış, "Login to GetStarted" Postman collection'ı ile birebir aynıdır:
  0. LoginForMobileBranch       → cihaz kaydı
  1. InitialLogin               → session_key1, token1
  2. SendSmsOtp                 (token1)
  3. OtpLoginCompleteNew        → session_key2, token2 (sabit test OTP'si)
  4. ChatBotInsertConversation  → istemcide üretilen GUID ile yeni sohbet
  5. Chat/Message               → asistanın cevabı (aynı conversationId ile)

Login run başına bir kez yapılır. Token'lar 5 dk geçerli olduğu için süresi
dolmadan (token_refresh_seconds) yeniden login olunur; conversationId korunur.
"""

import logging
import time
import uuid

import requests

from ..config import AssistantConfig, Credentials
from .reply import Reply, parse_reply

log = logging.getLogger(__name__)

AUTH_SERVICE = "/BOA.Integration.Authentication/AuthenticationService.svc/"
CHATBOT_SERVICE = "/BOA.Integration.MobileBanking.ChatBot/ChatBotService.svc/"


class AssistantError(Exception):
    pass


class AssistantClient:
    def __init__(self, cfg: AssistantConfig, creds: Credentials, http: requests.Session | None = None, clock=time.monotonic):
        self.cfg = cfg
        self.creds = creds
        self.http = http or requests.Session()
        self.clock = clock
        self.token: str | None = None
        self.session_key: str | None = None
        self.logged_in_at: float | None = None
        self.login_count = 0

    # ---------------------------------------------------------------- login
    def login(self) -> None:
        log.info("Login başlıyor (müşteri %s)", self.creds.customer_id)
        self._register_device()
        res = self._call_auth("InitialLogin", self._initial_login_body())
        token1, session_key1 = res["AuthenticationToken"], res["SessionKey"]
        self._call_auth("SendSmsOtp", self._send_otp_body(session_key1), token=token1)
        res = self._call_auth("OtpLoginCompleteNew", self._otp_complete_body(session_key1), token=token1)
        self.token = res["LoginResponse"]["AuthenticationToken"]
        self.session_key = res["LoginResponse"]["SessionKey"]
        self.logged_in_at = self.clock()
        self.login_count += 1
        log.info("Login tamam")

    def ensure_fresh(self) -> None:
        if self.logged_in_at is None or self.clock() - self.logged_in_at >= self.cfg.token_refresh_seconds:
            self.login()

    # ---------------------------------------------------------- conversation
    def new_conversation(self) -> "Conversation":
        """Yeni conversationId = modelde sıfırdan yeni bağlam."""
        self.ensure_fresh()
        conversation_id = str(uuid.uuid4())
        body = {
            **self._device_fields(),
            "MethodName": "ChatBotInsertConversation",
            "MainResourceCode": self.cfg.main_resource_code_dashboard,
            "MainResourceId": self.cfg.main_resource_id,
            "SessionType": 2,
            "ExtUName": self.creds.ext_u_name,
            "ExtUPassword": self.creds.ext_u_password,
            "ExtUSessionKey": self.session_key,
            "OwnerCustomerId": self.creds.customer_id,
            "ConversationId": conversation_id,
        }
        res = self._post_json(self.cfg.base_url + CHATBOT_SERVICE + "ChatBotInsertConversation", body, self.token)
        if res.get("Value") is not True:
            raise AssistantError(f"ChatBotInsertConversation başarısız: {_short(res)}")
        return Conversation(self, conversation_id)

    def send_message(self, conversation_id: str, text: str) -> Reply:
        self.ensure_fresh()
        resp = self._post_message(conversation_id, text)
        if resp.status_code == 401:
            log.info("Token reddedildi, yeniden login olunuyor")
            self.login()
            resp = self._post_message(conversation_id, text)
        if resp.status_code != 200:
            raise AssistantError(f"Chat/Message HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            raw = resp.json()
        except ValueError:
            raw = resp.text
        return parse_reply(raw)

    # ---------------------------------------------------------------- helpers
    def _post_message(self, conversation_id: str, text: str) -> requests.Response:
        data = {
            "channelId": str(self.cfg.channel_id),
            "conversationId": conversation_id,
            "text": text,
            "mobileToken": self.token,
            "languageId": str(self.cfg.language_id),
        }
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        return self.http.post(self.cfg.chatbot_message_url, data=data, headers=headers, timeout=self.cfg.timeout_seconds)

    def _register_device(self) -> None:
        d = self.cfg.device
        body = {
            "MethodName": "LoginForMobileBranch",
            "KcStatus": True,
            "AppName": d["app_name"],
            "Platform": 3,
            "DeviceOSVersion": d["device_os_version"],
            "LanguageId": self.cfg.language_id,
            "OperatorName": "--",
            "ExtUSessionKey": "",
            "SessionType": 1,
            "DeviceOSName": d["device_os_name"],
            "ExtUPassword": self.creds.reg_ext_u_password,
            "IsDeviceRooted": False,
            "UserId": self.creds.reg_user_id,
            "DeviceId": d["device_id"],
            "ExtUName": self.creds.reg_ext_u_name,
            "Version": d["app_version"],
            "NetworkConnectionType": "WiFi",
            "ThemeId": 0,
            "MobileApplicationName": d["mobile_application_name"],
            "DeviceModel": d["device_model"],
        }
        self._call_auth("LoginForMobileBranch", body)

    def _device_fields(self) -> dict:
        d = self.cfg.device
        return {
            "AppName": d["app_name"],
            "Version": d["app_version"],
            "DeviceId": d["device_id"],
            "DeviceModel": d["device_model"],
            "DeviceOSName": d["device_os_name"],
            "DeviceOSVersion": d["device_os_version"],
            "IsDeviceRooted": False,
            "NetworkConnectionType": "WiFi",
            "OperatorName": "--",
            "LanguageId": self.cfg.language_id,
            "ThemeId": 0,
            "KcStatus": True,
        }

    def _initial_login_body(self) -> dict:
        c, d = self.creds, self.cfg.device
        return {
            **self._device_fields(),
            "MethodName": "InitialLogin",
            "ExtUName": c.ext_u_name,
            "ExtUPassword": c.ext_u_password,
            "ExtUSessionKey": "",
            "IsPwfEnable": False,
            "IsMSISDNVerificationRequired": False,
            "SessionType": 2,
            "Password": c.password,
            "IsStsEnable": False,
            "IsStsLogin": False,
            "SecurityType": 2,
            "PlatformId": 3,
            "MainResourceCode": self.cfg.main_resource_code,
            "ContainsCustomerInfo": True,
            "LoginType": 2,
            "PwfApplicationName": d["pwf_application_name"],
            "GSMNumber": c.gsm_number,
            "CustomerId": c.customer_id,
            "IsSessionWithKeycloak": True,
            "ConfigurationAppName": d["mobile_application_name"],
            "IsPinValidate": True,
        }

    def _send_otp_body(self, session_key1: str) -> dict:
        c = self.creds
        return {
            **self._device_fields(),
            "MethodName": "SendSmsOtp",
            "SessionType": 2,
            "ExtUName": c.ext_u_name,
            "ExtUPassword": c.ext_u_password,
            "ExtUSessionKey": session_key1,
            "CustomerId": c.customer_id,
            "OwnerCustomerId": c.customer_id,
            "MainResourceCode": self.cfg.main_resource_code,
            "SmsContentType": 0,
        }

    def _otp_complete_body(self, session_key1: str) -> dict:
        c = self.creds
        return {
            **self._device_fields(),
            "MethodName": "OtpLoginCompleteNew",
            "SessionType": 2,
            "ExtUName": c.ext_u_name,
            "ExtUPassword": c.ext_u_password,
            "ExtUSessionKey": session_key1,
            "CustomerId": c.customer_id,
            "OwnerCustomerId": c.customer_id,
            "PlatformId": 3,
            "GeneratedOtp": c.otp,
            "Password": c.otp,
            "IsNewMobileMenu": True,
            "OtpType": 2,
            "MainResourceCode": self.cfg.main_resource_code,
        }

    def _call_auth(self, method: str, body: dict, token: str | None = None) -> dict:
        return self._post_json(self.cfg.base_url + AUTH_SERVICE + method, body, token)

    def _post_json(self, url: str, body: dict, token: str | None) -> dict:
        method = body.get("MethodName", url.rsplit("/", 1)[-1])
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = self.http.post(url, json=body, headers=headers, timeout=self.cfg.timeout_seconds)
        if resp.status_code != 200:
            raise AssistantError(f"{method} HTTP {resp.status_code}: {resp.text[:300]}")
        res = resp.json()
        if res.get("Success") is False:
            raise AssistantError(f"{method} başarısız: {_short(res)}")
        return res


class Conversation:
    """Tek bir sohbet: tüm turlar aynı conversationId ile gider."""

    def __init__(self, client: AssistantClient, conversation_id: str):
        self.client = client
        self.id = conversation_id

    def send(self, text: str) -> Reply:
        return self.client.send_message(self.id, text)


def _short(res: dict) -> str:
    # Token / session key gibi alanları hata mesajına taşımamak için sadece sonuç alanları
    keep = {k: res[k] for k in ("Success", "Value", "Results", "ErrorMessage", "Message") if k in res}
    return str(keep)[:300]
