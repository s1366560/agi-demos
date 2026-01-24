#!/usr/bin/env python3
"""
架构合规性检查脚本

检查代码是否符合六边形架构原则：
1. Domain 层不应该依赖其他层
2. Application 层不应该依赖 Infrastructure 层
3. Primary Adapters 不应该绕过 Application 层
"""

import re
import sys
from pathlib import Path


# 颜色输出
class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")


def print_error(msg: str):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")


def print_warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.RESET}")


def print_info(msg: str):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.RESET}")


def print_header(msg: str):
    print(f"\n{Colors.BOLD}{msg}{Colors.RESET}")
    print("=" * len(msg))


class ArchitectureChecker:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.src_dir = self.project_root / "src"
        self.violations = []

        # 定义层级目录
        self.domain_dir = self.src_dir / "domain"
        self.application_dir = self.src_dir / "application"
        self.infrastructure_dir = self.src_dir / "infrastructure"

    def check_all(self) -> bool:
        """运行所有检查"""
        print_header("MemStack 架构合规性检查")

        all_passed = True

        # 1. Domain 层检查
        print_header("1. Domain 层检查")
        if not self.check_domain_layer():
            all_passed = False

        # 2. Application 层检查
        print_header("2. Application 层检查")
        if not self.check_application_layer():
            all_passed = False

        # 3. Infrastructure 层检查
        print_header("3. Infrastructure 层检查")
        if not self.check_infrastructure_layer():
            all_passed = False

        # 4. Primary Adapters 检查
        print_header("4. Primary Adapters (Routers) 检查")
        if not self.check_primary_adapters():
            all_passed = False

        # 总结
        print_header("检查结果")
        if all_passed:
            print_success("所有架构检查通过！✨")
            return True
        else:
            print_error(f"发现 {len(self.violations)} 个架构违规！")
            return False

    def check_domain_layer(self) -> bool:
        """检查 Domain 层不应该依赖其他层"""
        print_info("检查 Domain 层不应该依赖 Application 或 Infrastructure 层...")

        violations = []

        for py_file in self.domain_dir.rglob("*.py"):
            content = py_file.read_text()

            # 检查是否导入了 application 或 infrastructure
            if re.search(r"from src\.application\.", content):
                violations.append((py_file, "Domain 层不应依赖 Application 层"))

            if re.search(r"from src\.infrastructure\.", content):
                violations.append((py_file, "Domain 层不应依赖 Infrastructure 层"))

            # 允许导入标准库和 shared_kernel
            if re.search(r"from src\.domain\.shared_kernel", content):
                continue  # 这是允许的

        if violations:
            print_error(f"Domain 层有 {len(violations)} 个违规：")
            for file_path, reason in violations:
                print(f"  - {file_path.relative_to(self.project_root)}: {reason}")
                self.violations.append((file_path, reason))
            return False
        else:
            print_success("Domain 层检查通过")
            return True

    def check_application_layer(self) -> bool:
        """检查 Application 层不应该依赖 Infrastructure 层"""
        print_info("检查 Application 层不应该依赖 Infrastructure 层...")

        violations = []

        # 检查 use_cases - 应该只依赖 domain
        use_cases_dir = self.application_dir / "use_cases"
        for py_file in use_cases_dir.rglob("*.py"):
            content = py_file.read_text()

            if re.search(r"from src\.infrastructure\.", content):
                violations.append((py_file, "Use Case 不应依赖 Infrastructure 层"))

        # 检查 services - 可以依赖 infrastructure adapters 实现
        # 但应该通过依赖注入，而不是直接导入
        services_dir = self.application_dir / "services"
        for py_file in services_dir.rglob("*.py"):
            content = py_file.read_text()

            # 允许导入接口（如果未来有的话）
            # 但不应该直接导入 persistence
            if re.search(r"from src\.infrastructure\.adapters\.secondary\.persistence", content):
                violations.append((py_file, "Service 不应直接依赖 Persistence 层"))

        if violations:
            print_error(f"Application 层有 {len(violations)} 个违规：")
            for file_path, reason in violations:
                rel_path = file_path.relative_to(self.project_root)
                print(f"  - {rel_path}: {reason}")
                self.violations.append((file_path, reason))
            return False
        else:
            print_success("Application 层检查通过")
            return True

    def check_infrastructure_layer(self) -> bool:
        """检查 Infrastructure 层实现正确性"""
        print_info("检查 Infrastructure 层实现...")

        issues = []

        # Secondary adapters 应该实现 domain ports
        secondary_dir = self.infrastructure_dir / "adapters" / "secondary"
        for py_file in secondary_dir.rglob("*.py"):
            content = py_file.read_text()

            # 应该导入 domain ports
            if "repository" in str(py_file).lower():
                if not re.search(r"from src\.domain\.ports\.repositories", content):
                    issues.append((py_file, "Repository 应该实现 Domain Ports 接口"))

            if "adapter" in str(py_file).lower():
                if not re.search(r"from src\.domain\.ports", content):
                    issues.append((py_file, "Adapter 应该实现 Domain Ports 接口"))

        if issues:
            print_warning(f"发现 {len(issues)} 个问题：")
            for file_path, reason in issues:
                print(f"  - {file_path.relative_to(self.project_root)}: {reason}")
            # 不算违规，只是警告
            return True
        else:
            print_success("Infrastructure 层检查通过")
            return True

    def check_primary_adapters(self) -> bool:
        """检查 Primary Adapters (Routers) 不应绕过 Application 层"""
        print_info("检查 Routers 不应直接访问数据库...")

        violations = []

        routers_dir = self.infrastructure_dir / "adapters" / "primary" / "web" / "routers"
        for py_file in routers_dir.glob("*.py"):
            content = py_file.read_text()

            # Skip if file uses DI container (indicates proper refactoring)
            uses_di_container = re.search(
                r"from src\.configuration\.di_container import|DIContainer", content
            )

            # Allow get_db for DI container purposes
            # Allow User model for FastAPI dependencies
            # Check if router uses use cases OR DI container
            uses_use_cases = re.search(r"from src\.application\.use_cases", content)

            # Check for problematic direct persistence usage (not through use cases)
            direct_db_usage = False

            # Look for direct session.execute() without use case wrapper
            # This pattern indicates direct DB access
            if re.search(r"db\.execute\(|session\.execute\(", content) and not uses_di_container:
                # But allow it if it's wrapped in a repository or service
                if not re.search(r"Repository|Service", content):
                    direct_db_usage = True

            # Check if directly importing persistence models for business logic
            # (User model is OK for dependencies, other models for direct manipulation are not)
            problematic_model_imports = []
            for match in re.finditer(
                r"from src\.infrastructure\.adapters\.secondary\.persistence\.models import ([^\n]+)",
                content,
            ):
                imports = match.group(1)
                # User is OK for dependencies, others are suspicious
                suspicious = [
                    m.strip() for m in imports.split(",") if m.strip() and "User" not in m
                ]
                if suspicious and not uses_use_cases and not uses_di_container:
                    problematic_model_imports.extend(suspicious)

            # Report violations
            if not uses_use_cases and not uses_di_container:
                if py_file.name != "__init__.py":  # Skip __init__
                    violations.append((py_file, "Router 应该调用 Use Cases 或使用 DI 容器"))

            if problematic_model_imports and not uses_use_cases and not uses_di_container:
                violations.append(
                    (
                        py_file,
                        f"Router 直接使用数据库模型进行业务逻辑: {', '.join(set(problematic_model_imports))}",
                    )
                )

            if direct_db_usage and not uses_use_cases and not uses_di_container:
                violations.append((py_file, "Router 直接操作数据库，应通过 Use Cases"))

        if violations:
            print_error(f"Routers 有 {len(violations)} 个违规：")
            for file_path, reason in violations:
                rel_path = file_path.relative_to(self.project_root)
                print(f"  - {rel_path}")
                print(f"    原因: {reason}")
                self.violations.append((file_path, reason))
            return False
        else:
            print_success("Routers 检查通过")
            return True


def main():
    """主函数"""

    # 默认检查当前目录
    project_root = Path.cwd()

    # 如果提供了参数，使用参数作为项目根目录
    if len(sys.argv) > 1:
        project_root = Path(sys.argv[1])

    if not (project_root / "src").exists():
        print_error(f"找不到 src/ 目录: {project_root}")
        sys.exit(1)

    print(f"检查项目: {project_root}")
    print()

    checker = ArchitectureChecker(str(project_root))
    passed = checker.check_all()

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
