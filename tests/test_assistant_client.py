import pytest

from assisteval.simulator.assistant_client import AssistantClient, AssistantError
from assisteval.cli import MOCK_CREDS
from assisteval.config import AssistantConfig
from assisteval.simulator.mock_assistant import MockBank, MockServer

DEVICE = {
    "device_id": "TEST-DEVICE", "device_model": "iPhone", "device_os_name": "IOS", "device_os_version": "26.6",
    "app_name": "IOS MobileBranch", "app_version": "7.2.5", "mobile_application_name": "OrganikProd",
    "pwf_application_name": "KTIOSDev",
}


@pytest.fixture
def server():
    with MockServer(MockBank()) as srv:
        yield srv


def make_client(srv, creds=MOCK_CREDS, clock=None, **kw):
    cfg = AssistantConfig(
        base_url=srv.base_url, chatbot_message_url=srv.chatbot_message_url, device=DEVICE,
        main_resource_code="MOBRMAINPG", main_resource_code_dashboard="MOBRDASHBO", main_resource_id=22027, **kw,
    )
    return AssistantClient(cfg, creds, **({"clock": clock} if clock else {}))


def test_full_flow_keeps_context_per_conversation(server):
    client = make_client(server)
    conv = client.new_conversation()
    assert "Merhaba" in conv.send("/get_started").text
    assert "Kime" in conv.send("Para göndermek istiyorum").text
    assert "ne kadar" in conv.send("Ahmet Yılmaz").text  # aynı conversationId → bağlam korunuyor

    other = client.new_conversation()  # yeni conversationId → sıfırdan bağlam
    assert other.id != conv.id
    assert "anlayamadım" in other.send("Ahmet Yılmaz").text
    assert client.login_count == 1


def test_relogin_before_token_expires(server):
    now = [0.0]
    client = make_client(server, clock=lambda: now[0], token_refresh_seconds=240)
    conv = client.new_conversation()
    conv.send("/get_started")
    now[0] = 241
    conv.send("Kampanya listele")
    assert client.login_count == 2


def test_relogin_on_401(server):
    client = make_client(server)
    conv = client.new_conversation()
    server.bank.tokens.clear()  # sunucu tarafında token düştü
    assert "Merhaba" in conv.send("/get_started").text
    assert client.login_count == 2


def test_wrong_otp_fails(server):
    from dataclasses import replace

    client = make_client(server, creds=replace(MOCK_CREDS, otp="000000"))
    with pytest.raises(AssistantError, match="OtpLoginCompleteNew"):
        client.login()
