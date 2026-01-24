"""Agent use cases module.

This module contains the use cases for agent-related operations.
"""

from src.application.use_cases.agent.chat import ChatUseCase
from src.application.use_cases.agent.compose_tools import ComposeToolsUseCase
from src.application.use_cases.agent.create_conversation import CreateConversationUseCase
from src.application.use_cases.agent.enter_plan_mode import EnterPlanModeUseCase
from src.application.use_cases.agent.execute_step import ExecuteStepUseCase
from src.application.use_cases.agent.exit_plan_mode import ExitPlanModeUseCase
from src.application.use_cases.agent.find_similar_pattern import FindSimilarPattern
from src.application.use_cases.agent.get_conversation import GetConversationUseCase
from src.application.use_cases.agent.get_plan import GetPlanUseCase
from src.application.use_cases.agent.learn_pattern import LearnPattern
from src.application.use_cases.agent.list_conversations import ListConversationsUseCase
from src.application.use_cases.agent.plan_work import PlanWorkUseCase
from src.application.use_cases.agent.synthesize_results import SynthesizeResultsUseCase
from src.application.use_cases.agent.update_plan import UpdatePlanUseCase

__all__ = [
    "CreateConversationUseCase",
    "ListConversationsUseCase",
    "GetConversationUseCase",
    "ChatUseCase",
    "PlanWorkUseCase",
    "ExecuteStepUseCase",
    "SynthesizeResultsUseCase",
    "FindSimilarPattern",
    "LearnPattern",
    "ComposeToolsUseCase",
    "EnterPlanModeUseCase",
    "ExitPlanModeUseCase",
    "UpdatePlanUseCase",
    "GetPlanUseCase",
]
