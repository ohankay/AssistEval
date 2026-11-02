"""Simülasyonu kuran ortak parçalar: CLI ve promptfoo provider'ı aynı yoldan geçer."""

from .config import Credentials, Settings
from .simulator.assistant_client import AssistantClient
from .simulator.llm import OpenAICompatibleLLM
from .simulator.scenario import Scenario
from .simulator.user import LLMUser, ScriptUser


def assistant_client(settings: Settings) -> AssistantClient:
    """config.yaml'daki asistana .env'deki bilgilerle bağlanan istemci."""
    return AssistantClient(settings.assistant, Credentials.from_env())


def simulated_user(scenario: Scenario, settings: Settings):
    """(simüle müşteri, kullanılan LLM'in adı) döner; script modunda LLM yoktur."""
    if scenario.mod == "script":
        return ScriptUser(scenario), None
    llm = OpenAICompatibleLLM(settings.simulator)
    return LLMUser(scenario, llm), llm.name
