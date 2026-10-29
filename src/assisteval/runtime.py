"""Simülasyonu kuran ortak parçalar: CLI ve promptfoo provider'ı aynı yoldan geçer."""

import contextlib
from dataclasses import replace

from .config import Credentials, Settings
from .simulator.assistant_client import AssistantClient
from .simulator.llm import MockLLM, OpenAICompatibleLLM
from .simulator.mock_assistant import MockServer
from .simulator.scenario import Scenario
from .simulator.user import LLMUser, ScriptUser

MOCK_CREDS = Credentials(
    customer_id="00000000", gsm_number="900000000000", password="121212", otp="121212",
    ext_u_name="mock", ext_u_password="mock", reg_ext_u_name="mock", reg_ext_u_password="mock", reg_user_id="mock",
)


@contextlib.contextmanager
def assistant_client(settings: Settings, mode: str):
    """mode: "real" → gerçek asistan (.env'deki bilgilerle), "mock" → arka planda sahte sunucu."""
    if mode == "real":
        yield AssistantClient(settings.assistant, Credentials.from_env())
        return
    with MockServer() as srv:
        cfg = replace(settings.assistant, base_url=srv.base_url, chatbot_message_url=srv.chatbot_message_url)
        yield AssistantClient(cfg, MOCK_CREDS)


def simulated_user(scenario: Scenario, settings: Settings, llm_choice: str):
    """(simüle müşteri, kullanılan LLM'in adı) döner; script modunda LLM yoktur."""
    if scenario.mod == "script":
        return ScriptUser(scenario), None
    llm = MockLLM(scenario.yonlendirme) if llm_choice == "mock" else OpenAICompatibleLLM(settings.llm)
    return LLMUser(scenario, llm), llm.name
