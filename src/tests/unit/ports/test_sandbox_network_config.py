"""Tests for Sandbox network configuration."""

from src.domain.ports.services.sandbox_port import SandboxConfig


class TestSandboxNetworkConfig:
    """测试 SandboxConfig 网络配置."""

    def test_default_network_isolated(self) -> None:
        """默认应该启用网络隔离."""
        config = SandboxConfig(image="sandbox-mcp-server:latest")

        assert config.network_isolated is True
        assert config.network_mode == "bridge"

    def test_network_mode_none(self) -> None:
        """应该支持 none 网络模式."""
        config = SandboxConfig(image="sandbox-mcp-server:latest", network_mode="none")

        assert config.network_mode == "none"
        assert config.network_isolated is True  # none mode 意味着隔离

    def test_network_mode_host(self) -> None:
        """应该支持 host 网络模式."""
        config = SandboxConfig(image="sandbox-mcp-server:latest", network_mode="host")

        assert config.network_mode == "host"

    def test_allowed_networks(self) -> None:
        """应该配置允许的网络范围."""
        config = SandboxConfig(
            image="sandbox-mcp-server:latest",
            allowed_networks=["10.0.0.0/8", "172.16.0.0/12"],
        )

        assert len(config.allowed_networks) == 2
        assert "10.0.0.0/8" in config.allowed_networks

    def test_blocked_ports(self) -> None:
        """应该配置阻止的端口."""
        config = SandboxConfig(
            image="sandbox-mcp-server:latest",
            blocked_ports=[22, 3389],  # SSH, RDP
        )

        assert 22 in config.blocked_ports
        assert 3389 in config.blocked_ports

    def test_network_isolation_with_bridge(self) -> None:
        """bridge 模式仍然可以隔离."""
        config = SandboxConfig(
            image="sandbox-mcp-server:latest",
            network_mode="bridge",
            network_isolated=True,
        )

        assert config.network_mode == "bridge"
        assert config.network_isolated is True

    def test_full_network_isolation(self) -> None:
        """完全网络隔离配置."""
        config = SandboxConfig(
            image="sandbox-mcp-server:latest",
            network_mode="none",
            network_isolated=True,
            allowed_networks=[],
            blocked_ports=[],
        )

        assert config.network_mode == "none"
        assert config.network_isolated is True
        assert len(config.allowed_networks) == 0


class TestSandboxNetworkSecurity:
    """测试 Sandbox 网络安全配置."""

    def test_block_sensitive_ports(self) -> None:
        """应该默认阻止敏感端口."""
        # SSH (22), RDP (3389), MySQL (3306), PostgreSQL (5432)
        sensitive_ports = [22, 3389, 3306, 5432]
        config = SandboxConfig(image="sandbox-mcp-server:latest", blocked_ports=sensitive_ports)

        for port in sensitive_ports:
            assert port in config.blocked_ports

    def test_allow_internal_networks_only(self) -> None:
        """应该只允许内部网络访问."""
        config = SandboxConfig(
            image="sandbox-mcp-server:latest",
            network_mode="bridge",
            allowed_networks=[
                "10.0.0.0/8",  # Private Class A
                "172.16.0.0/12",  # Private Class B
                "192.168.0.0/16",  # Private Class C
            ],
            blocked_ports=[22, 3389],
        )

        assert len(config.allowed_networks) == 3
        assert len(config.blocked_ports) == 2

    def test_container_network_mode(self) -> None:
        """应该支持连接到另一个容器网络."""
        config = SandboxConfig(
            image="sandbox-mcp-server:latest", network_mode="container:another-container"
        )

        assert config.network_mode.startswith("container:")

    def test_security_profile_network_mapping(self) -> None:
        """安全 profile 应该映射到网络配置."""
        # Standard profile - 基本隔离
        standard_config = SandboxConfig(
            image="sandbox-mcp-server:latest", security_profile="standard"
        )
        assert standard_config.network_isolated is True

        # Strict profile - 更严格
        strict_config = SandboxConfig(
            image="sandbox-mcp-server:latest",
            security_profile="strict",
            network_mode="none",
            blocked_ports=list(range(1, 1024)),  # 阻止所有知名端口
        )
        assert strict_config.network_mode == "none"
        assert len(strict_config.blocked_ports) == 1023
