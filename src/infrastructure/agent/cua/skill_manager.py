"""
CUA Skill Manager.

Manages CUA-related skills for L2 (Skill Layer) integration.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from src.domain.model.agent.skill import Skill, SkillStatus

if TYPE_CHECKING:
    from .config import CUAConfig

logger = logging.getLogger(__name__)


class CUASkillManager:
    """
    Manager for CUA-related skills.

    This class provides:
    - Built-in CUA skills for common automation tasks
    - Skill registration and discovery
    - Skill execution coordination

    Skills are declarative compositions of CUA tools that can be
    triggered based on user intent patterns.
    """

    @staticmethod
    def get_builtin_skills(config: Optional["CUAConfig"] = None) -> List[Skill]:
        """
        Get built-in CUA skills.

        Args:
            config: Optional CUA configuration

        Returns:
            List of Skill instances
        """
        skills = []

        # Web Search Skill
        skills.append(
            Skill(
                id="cua_web_search",
                tenant_id="system",
                name="cua_web_search_skill",
                description=(
                    "Search for information on the web using the browser. "
                    "Opens a search engine, enters the query, and extracts results."
                ),
                tools=["cua_browser_navigate", "cua_type", "cua_click", "cua_screenshot"],
                triggers=[
                    "在网页上搜索",
                    "打开浏览器搜索",
                    "搜索网页",
                    "查找网页信息",
                    "search on web",
                    "search the internet",
                    "google search",
                    "web search",
                ],
                prompt_template=(
                    "Use CUA to search the web:\n"
                    "1. Navigate to a search engine (e.g., https://www.google.com)\n"
                    "2. Enter the search query\n"
                    "3. Click the search button\n"
                    "4. Take a screenshot of results\n"
                    "5. Extract relevant information"
                ),
                status=SkillStatus.ACTIVE,
            )
        )

        # Form Fill Skill
        skills.append(
            Skill(
                id="cua_form_fill",
                tenant_id="system",
                name="cua_form_fill_skill",
                description=(
                    "Fill out forms on web pages. Identifies form fields, enters data, and submits."
                ),
                tools=["cua_click", "cua_type", "cua_screenshot"],
                triggers=[
                    "填写表单",
                    "输入信息到网页",
                    "填写网页",
                    "fill form",
                    "fill out form",
                    "enter form data",
                    "submit form",
                ],
                prompt_template=(
                    "Use CUA to fill a form:\n"
                    "1. Take a screenshot to identify form fields\n"
                    "2. Click on each field and enter the appropriate data\n"
                    "3. Verify entered data with screenshot\n"
                    "4. Click submit button if requested"
                ),
                status=SkillStatus.ACTIVE,
            )
        )

        # UI Automation Skill
        skills.append(
            Skill(
                id="cua_ui_automation",
                tenant_id="system",
                name="cua_ui_automation_skill",
                description=(
                    "Automate UI interactions like clicking buttons, "
                    "navigating menus, and operating desktop applications."
                ),
                tools=["cua_click", "cua_type", "cua_scroll", "cua_screenshot"],
                triggers=[
                    "点击按钮",
                    "操作界面",
                    "自动化任务",
                    "操作应用程序",
                    "click button",
                    "operate UI",
                    "automate task",
                    "use application",
                ],
                prompt_template=(
                    "Use CUA for UI automation:\n"
                    "1. Take a screenshot to understand current state\n"
                    "2. Identify the target UI element\n"
                    "3. Perform the required action (click, type, scroll)\n"
                    "4. Verify the result with another screenshot"
                ),
                status=SkillStatus.ACTIVE,
            )
        )

        # Screenshot Analysis Skill
        skills.append(
            Skill(
                id="cua_screenshot_analyze",
                tenant_id="system",
                name="cua_screenshot_analyze_skill",
                description=(
                    "Capture and analyze the current screen state. "
                    "Identifies UI elements, text, and layout."
                ),
                tools=["cua_screenshot"],
                triggers=[
                    "截图",
                    "查看屏幕",
                    "分析界面",
                    "看看屏幕",
                    "take screenshot",
                    "capture screen",
                    "analyze screen",
                    "what's on screen",
                ],
                prompt_template=(
                    "Use CUA to capture and analyze the screen:\n"
                    "1. Take a screenshot\n"
                    "2. Describe what's visible on screen\n"
                    "3. Identify key UI elements and their positions"
                ),
                status=SkillStatus.ACTIVE,
            )
        )

        # File Download Skill
        skills.append(
            Skill(
                id="cua_file_download",
                tenant_id="system",
                name="cua_file_download_skill",
                description=(
                    "Download files from web pages. "
                    "Navigates to URL, finds download link, and initiates download."
                ),
                tools=["cua_browser_navigate", "cua_click", "cua_screenshot"],
                triggers=[
                    "下载文件",
                    "从网页下载",
                    "download file",
                    "download from web",
                    "save file",
                ],
                prompt_template=(
                    "Use CUA to download a file:\n"
                    "1. Navigate to the download page\n"
                    "2. Find the download link/button\n"
                    "3. Click to initiate download\n"
                    "4. Verify download started"
                ),
                status=SkillStatus.ACTIVE,
            )
        )

        logger.info(f"Loaded {len(skills)} built-in CUA skills")
        return skills

    @staticmethod
    def get_skill_by_name(name: str, config: Optional["CUAConfig"] = None) -> Optional[Skill]:
        """
        Get a skill by name.

        Args:
            name: Skill name
            config: Optional CUA configuration

        Returns:
            Skill instance or None if not found
        """
        skills = CUASkillManager.get_builtin_skills(config)
        for skill in skills:
            if skill.name == name or skill.id == name:
                return skill
        return None

    @staticmethod
    def get_skills_for_query(query: str, config: Optional["CUAConfig"] = None) -> List[Skill]:
        """
        Get skills that match a query based on triggers.

        Args:
            query: User query
            config: Optional CUA configuration

        Returns:
            List of matching skills
        """
        skills = CUASkillManager.get_builtin_skills(config)
        matches = []

        query_lower = query.lower()
        for skill in skills:
            for trigger in skill.triggers:
                if trigger.lower() in query_lower or query_lower in trigger.lower():
                    matches.append(skill)
                    break

        return matches
