"""
SKILL Resource Loader.

Scans SKILL directories and detects resources that need to be injected
into remote Sandbox containers.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Set

from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

logger = logging.getLogger(__name__)


class SkillResourceLoader:
    """
    SKILL 资源加载器

    扫描 SKILL 目录，检测需要注入的资源
    """

    # 资源目录名称
    RESOURCE_DIRS = ["scripts", "references", "assets"]

    # SKILL.md 中常见的资源引用模式
    RESOURCE_PATTERNS = [
        r'scripts/[\w./\-]+',      # scripts/xxx.py
        r'references/[\w./\-]+',   # references/xxx.md
        r'assets/[\w./\-]+',       # assets/xxx.png
    ]

    def __init__(
        self,
        project_path: Path,
        scanner: Optional[FileSystemSkillScanner] = None,
    ):
        """
        Initialize the resource loader.

        Args:
            project_path: Project root path
            scanner: Optional custom scanner (defaults to FileSystemSkillScanner)
        """
        self.project_path = Path(project_path)
        self.scanner = scanner or FileSystemSkillScanner()

    async def get_skill_resources(
        self,
        skill_name: str,
    ) -> List[Path]:
        """
        获取 SKILL 的所有资源文件

        Args:
            skill_name: SKILL 名称

        Returns:
            资源文件路径列表
        """
        # 查找 SKILL 目录
        file_info = self.scanner.find_skill(
            self.project_path,
            skill_name,
            include_global=True,
            include_system=True,
        )

        if not file_info:
            return []

        resources = []
        skill_dir = file_info.skill_dir

        # 扫描资源目录
        for dir_name in self.RESOURCE_DIRS:
            resource_dir = skill_dir / dir_name
            if resource_dir.exists() and resource_dir.is_dir():
                resources.extend(self._scan_directory(resource_dir))

        return resources

    def _scan_directory(self, directory: Path) -> List[Path]:
        """
        递归扫描目录中的所有文件

        Args:
            directory: Directory to scan

        Returns:
            List of file paths
        """
        resources = []
        try:
            for item in directory.rglob("*"):
                if item.is_file():
                    resources.append(item)
        except Exception as e:
            logger.warning(f"Error scanning directory {directory}: {e}")

        return resources

    async def detect_referred_resources(
        self,
        skill_name: str,
        skill_content: str,
    ) -> Set[str]:
        """
        从 SKILL.md 内容中检测引用的资源路径

        Args:
            skill_name: SKILL 名称
            skill_content: SKILL.md 内容

        Returns:
            资源路径集合
        """
        referred = set()

        for pattern in self.RESOURCE_PATTERNS:
            matches = re.findall(pattern, skill_content)
            referred.update(matches)

        return referred

    def get_resource_container_path(
        self,
        skill_name: str,
        resource_path: Path,
        skill_dir: Optional[Path] = None,
    ) -> str:
        """
        资源在 Sandbox 容器内的路径

        所有 SKILL 资源统一放在 /workspace/.memstack/skills/ 目录下

        Args:
            skill_name: SKILL 名称
            resource_path: 资源本地路径
            skill_dir: SKILL 目录（用于计算相对路径）

        Returns:
            容器内路径
        """
        if skill_dir:
            try:
                # 计算相对于 SKILL 目录的路径
                rel_path = resource_path.relative_to(skill_dir)
                return f"/workspace/.memstack/skills/{skill_name}/{rel_path}"
            except ValueError:
                pass

        # Fallback: 使用文件名
        return f"/workspace/.memstack/skills/{skill_name}/{resource_path.name}"
