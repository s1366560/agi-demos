"""
SKILL Resource Injector.

Injects local SKILL resources into remote Sandbox containers via MCP tools.
"""

import logging
from pathlib import Path

from src.domain.ports.services.sandbox_port import SandboxPort

from .skill_resource_loader import SkillResourceLoader

logger = logging.getLogger(__name__)


class SkillResourceInjector:
    """
    SKILL 资源注入器

    负责将本地 SKILL 资源注入到远程 Sandbox 容器
    """

    def __init__(
        self,
        resource_loader: SkillResourceLoader,
    ) -> None:
        """
        Initialize the injector.

        Args:
            resource_loader: Resource loader instance
        """
        self.loader = resource_loader
        self._injected_cache: dict[str, dict[str, dict[str, str]]] = {}

    async def inject_skill(
        self,
        sandbox_adapter: SandboxPort,
        sandbox_id: str,
        skill_name: str,
        skill_content: str | None = None,
    ) -> dict[str, str]:
        """
        注入 SKILL 的所有资源到 Sandbox

        Args:
            sandbox_adapter: Sandbox 适配器
            sandbox_id: Sandbox ID
            skill_name: SKILL 名称
            skill_content: SKILL.md 内容（用于检测引用）

        Returns:
            本地路径 -> 容器路径的映射
        """
        resource_paths = await self.loader.get_skill_resources(skill_name)

        if not resource_paths:
            logger.debug(f"No resources found for skill: {skill_name}")
            return {}

        path_mapping: dict[str, str] = {}

        for resource_path in resource_paths:
            try:
                # 读取资源内容
                content = resource_path.read_text(encoding="utf-8")

                # 构建容器内路径
                skill_dir = self._get_skill_dir_for_resource(resource_path, skill_name)
                container_path = self.loader.get_resource_container_path(
                    skill_name, resource_path, skill_dir
                )

                # 写入 Sandbox (去掉 /workspace/ 前缀，因为 MCP 工具使用相对路径)
                relative_path = container_path.replace("/workspace/", "")

                result = await sandbox_adapter.call_tool(
                    sandbox_id=sandbox_id,
                    tool_name="write",
                    arguments={
                        "file_path": relative_path,
                        "content": content,
                    },
                )

                if not result.get("isError"):
                    path_mapping[str(resource_path)] = container_path
                    logger.debug(f"Injected resource: {resource_path} -> {container_path}")
                else:
                    logger.warning(f"Failed to inject {resource_path}: {result}")
                    continue  # Skip adding to path_mapping on error

            except Exception as e:
                logger.error(f"Failed to inject resource {resource_path}: {e}")

        # 缓存映射
        self._injected_cache.setdefault(sandbox_id, {})[skill_name] = path_mapping

        return path_mapping

    def _get_skill_dir_for_resource(self, resource_path: Path, skill_name: str) -> Path | None:
        """
        获取资源所属的 SKILL 目录

        Args:
            resource_path: 资源文件路径
            skill_name: SKILL 名称

        Returns:
            SKILL 目录路径，如果无法确定则返回 None
        """
        # 遍历父目录，找到包含 SKILL.md 的目录
        current = resource_path.parent
        while current != current.parent:  # 根目录的父节点是它自己
            if (current / "SKILL.md").exists():
                return current
            current = current.parent
        return None

    async def setup_skill_environment(
        self,
        sandbox_adapter: SandboxPort,
        sandbox_id: str,
        skill_name: str,
    ) -> bool:
        """
        设置 SKILL 执行环境

        在 Sandbox 中设置环境变量，使 SKILL 中的相对路径能正确解析

        Args:
            sandbox_adapter: Sandbox 适配器
            sandbox_id: Sandbox ID
            skill_name: SKILL 名称

        Returns:
            True if setup succeeded
        """
        # 创建环境设置脚本
        setup_script = f"""#!/bin/bash
# SKILL environment setup for {skill_name}
export SKILL_ROOT="/workspace/.memstack/skills/{skill_name}"
export PATH="$SKILL_ROOT/scripts:$PATH"
"""

        result = await sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="write",
            arguments={
                "file_path": f".memstack/skills/{skill_name}/env.sh",
                "content": setup_script,
            },
        )

        return not result.get("isError")

    def get_injected_resources(
        self,
        sandbox_id: str,
        skill_name: str,
    ) -> dict[str, str]:
        """
        获取已注入的资源映射

        Args:
            sandbox_id: Sandbox ID
            skill_name: SKILL 名称

        Returns:
            本地路径 -> 容器路径的映射
        """
        return self._injected_cache.get(sandbox_id, {}).get(skill_name, {})
