"""Docker Sandbox Adapter - Implementation of SandboxPort using Docker containers."""

import asyncio
import io
import logging
import tarfile
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

import docker
from docker.errors import ImageNotFound, NotFound

from src.domain.ports.services.sandbox_port import (
    CodeExecutionRequest,
    CodeExecutionResult,
    SandboxConfig,
    SandboxConnectionError,
    SandboxInstance,
    SandboxNotFoundError,
    SandboxPort,
    SandboxStatus,
    SandboxTimeoutError,
)

logger = logging.getLogger(__name__)


class DockerSandboxAdapter(SandboxPort):
    """
    Docker-based sandbox implementation.

    Creates isolated Docker containers for code execution with resource limits
    and security controls.
    """

    # Default images for different sandbox types
    DEFAULT_IMAGES = {
        "python": "python:3.12-slim",
        "node": "node:20-slim",
        "default": "python:3.12-slim",
    }

    def __init__(
        self,
        default_image: str = "python:3.12-slim",
        default_timeout: int = 60,
        default_memory_limit: str = "2g",
        default_cpu_limit: str = "2",
        network_isolated: bool = True,
    ):
        """
        Initialize Docker sandbox adapter.

        Args:
            default_image: Default Docker image for sandboxes
            default_timeout: Default execution timeout in seconds
            default_memory_limit: Default memory limit (e.g., "2g")
            default_cpu_limit: Default CPU limit
            network_isolated: Whether to isolate network by default
        """
        self._default_image = default_image
        self._default_timeout = default_timeout
        self._default_memory_limit = default_memory_limit
        self._default_cpu_limit = default_cpu_limit
        self._network_isolated = network_isolated

        # Track active sandboxes
        self._active_sandboxes: Dict[str, SandboxInstance] = {}

        # Initialize Docker client
        try:
            self._docker = docker.from_env()
            logger.info("DockerSandboxAdapter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise SandboxConnectionError(
                message=f"Failed to connect to Docker: {e}",
                operation="init",
            )

    async def create_sandbox(
        self,
        project_path: str,
        config: Optional[SandboxConfig] = None,
    ) -> SandboxInstance:
        """Create a new Docker container sandbox."""
        config = config or SandboxConfig()
        sandbox_id = f"sandbox-{uuid.uuid4().hex[:12]}"

        try:
            # Prepare container configuration
            image = config.image or self._default_image
            timeout = config.timeout_seconds or self._default_timeout

            # Container run configuration
            container_config = {
                "image": image,
                "name": sandbox_id,
                "detach": True,
                "stdin_open": True,
                "tty": True,
                "working_dir": "/workspace",
                "mem_limit": config.memory_limit or self._default_memory_limit,
                "cpu_quota": int(float(config.cpu_limit or self._default_cpu_limit) * 100000),
                "environment": {
                    "SANDBOX_ID": sandbox_id,
                    "TIMEOUT_SECONDS": str(timeout),
                    **config.environment,
                },
                # Security options
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "read_only": False,  # Need write access for /output
            }

            # Network isolation
            if config.network_isolated:
                container_config["network_mode"] = "none"

            # Volume mounts
            if project_path and project_path != "/tmp/sandbox_workspace":
                container_config["volumes"] = {
                    project_path: {"bind": "/workspace/project", "mode": "ro"}
                }

            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._docker.containers.run(**container_config),
            )

            # Create instance record
            instance = SandboxInstance(
                id=sandbox_id,
                status=SandboxStatus.RUNNING,
                config=config,
                project_path=project_path,
                endpoint=None,
                created_at=datetime.now(),
            )

            self._active_sandboxes[sandbox_id] = instance
            logger.info(f"Created sandbox: {sandbox_id} with image {image}")

            return instance

        except ImageNotFound:
            logger.error(f"Sandbox image not found: {config.image}")
            raise SandboxConnectionError(
                message=f"Docker image not found: {config.image}. Run: docker pull {config.image}",
                sandbox_id=sandbox_id,
                operation="create",
            )
        except Exception as e:
            logger.error(f"Failed to create sandbox: {e}")
            raise SandboxConnectionError(
                message=f"Failed to create sandbox: {e}",
                sandbox_id=sandbox_id,
                operation="create",
            )

    async def get_sandbox(self, sandbox_id: str) -> Optional[SandboxInstance]:
        """Get sandbox instance by ID."""
        if sandbox_id in self._active_sandboxes:
            # Update status from Docker
            try:
                loop = asyncio.get_event_loop()
                container = await loop.run_in_executor(
                    None,
                    lambda: self._docker.containers.get(sandbox_id),
                )

                instance = self._active_sandboxes[sandbox_id]
                status_map = {
                    "running": SandboxStatus.RUNNING,
                    "exited": SandboxStatus.STOPPED,
                    "created": SandboxStatus.CREATING,
                }
                instance.status = status_map.get(container.status, SandboxStatus.ERROR)
                return instance

            except NotFound:
                # Container was removed externally
                del self._active_sandboxes[sandbox_id]
                return None
            except Exception as e:
                logger.warning(f"Error getting sandbox status: {e}")
                return self._active_sandboxes.get(sandbox_id)

        return None

    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """Terminate a sandbox container."""
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            # Stop and remove container
            await loop.run_in_executor(None, lambda: container.stop(timeout=5))
            await loop.run_in_executor(None, container.remove)

            # Update tracking
            if sandbox_id in self._active_sandboxes:
                self._active_sandboxes[sandbox_id].status = SandboxStatus.TERMINATED
                self._active_sandboxes[sandbox_id].terminated_at = datetime.now()
                del self._active_sandboxes[sandbox_id]

            logger.info(f"Terminated sandbox: {sandbox_id}")
            return True

        except NotFound:
            logger.warning(f"Sandbox not found for termination: {sandbox_id}")
            if sandbox_id in self._active_sandboxes:
                del self._active_sandboxes[sandbox_id]
            return False
        except Exception as e:
            logger.error(f"Error terminating sandbox {sandbox_id}: {e}")
            return False

    async def execute_code(
        self,
        request: CodeExecutionRequest,
    ) -> CodeExecutionResult:
        """Execute code in a sandbox container."""
        start_time = time.time()

        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(request.sandbox_id),
            )

            # Ensure /output directory exists for file generation
            await loop.run_in_executor(
                None,
                lambda: container.exec_run("mkdir -p /output", user="root"),
            )

            # Prepare code execution command
            if request.language == "python":
                # Write code to a temp file and execute
                code_escaped = request.code.replace("'", "'\\''")
                cmd = f"python3 -c '{code_escaped}'"
            else:
                cmd = request.code

            # Execute with timeout
            timeout = request.timeout_seconds or 60

            try:
                exec_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: container.exec_run(
                            cmd,
                            workdir=request.working_directory,
                            environment=request.environment,
                            demux=True,
                        ),
                    ),
                    timeout=timeout,
                )

                exit_code = exec_result.exit_code
                stdout_bytes, stderr_bytes = exec_result.output

                stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
                stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

            except asyncio.TimeoutError:
                raise SandboxTimeoutError(
                    message=f"Code execution timed out after {timeout}s",
                    sandbox_id=request.sandbox_id,
                    operation="execute",
                )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # List output files
            output_files = await self._list_output_files(request.sandbox_id)

            return CodeExecutionResult(
                success=exit_code == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                execution_time_ms=execution_time_ms,
                output_files=output_files,
                error=stderr if exit_code != 0 else None,
            )

        except NotFound:
            raise SandboxNotFoundError(
                message=f"Sandbox not found: {request.sandbox_id}",
                sandbox_id=request.sandbox_id,
                operation="execute",
            )
        except SandboxTimeoutError:
            raise
        except Exception as e:
            logger.error(f"Code execution error: {e}")
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                execution_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def stream_execute(
        self,
        request: CodeExecutionRequest,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream code execution output."""
        # For now, use non-streaming execution and yield result
        result = await self.execute_code(request)

        if result.stdout:
            yield {"type": "stdout", "data": result.stdout}
        if result.stderr:
            yield {"type": "stderr", "data": result.stderr}

        yield {
            "type": "status",
            "data": {
                "success": result.success,
                "exit_code": result.exit_code,
                "execution_time_ms": result.execution_time_ms,
                "output_files": result.output_files,
            },
        }

    async def list_sandboxes(
        self,
        status: Optional[SandboxStatus] = None,
    ) -> List[SandboxInstance]:
        """List all sandbox instances."""
        result = []
        for instance in self._active_sandboxes.values():
            if status is None or instance.status == status:
                result.append(instance)
        return result

    async def get_output_files(
        self,
        sandbox_id: str,
        output_dir: str = "/output",
    ) -> Dict[str, bytes]:
        """Retrieve output files from sandbox."""
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            # Get archive from container
            try:
                archive_data, _ = await loop.run_in_executor(
                    None,
                    lambda: container.get_archive(output_dir),
                )

                # Extract files from tar archive
                files = {}
                tar_bytes = b"".join(archive_data)

                with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            f = tar.extractfile(member)
                            if f:
                                # Remove the leading directory name
                                name = (
                                    member.name.split("/", 1)[-1]
                                    if "/" in member.name
                                    else member.name
                                )
                                files[name] = f.read()

                logger.debug(f"Retrieved {len(files)} output files from sandbox {sandbox_id}")
                return files

            except Exception as e:
                logger.warning(f"No output files in {output_dir}: {e}")
                return {}

        except NotFound:
            raise SandboxNotFoundError(
                message=f"Sandbox not found: {sandbox_id}",
                sandbox_id=sandbox_id,
                operation="get_output_files",
            )

    async def cleanup_expired(
        self,
        max_age_seconds: int = 3600,
    ) -> int:
        """Clean up expired sandbox instances."""
        now = datetime.now()
        expired_ids = []

        for sandbox_id, instance in self._active_sandboxes.items():
            age = (now - instance.created_at).total_seconds()
            if age > max_age_seconds:
                expired_ids.append(sandbox_id)

        count = 0
        for sandbox_id in expired_ids:
            if await self.terminate_sandbox(sandbox_id):
                count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired sandboxes")

        return count

    async def _list_output_files(self, sandbox_id: str) -> List[str]:
        """List files in the output directory."""
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            result = await loop.run_in_executor(
                None,
                lambda: container.exec_run("ls -1 /output 2>/dev/null || true"),
            )

            if result.exit_code == 0:
                output = result.output.decode("utf-8", errors="replace")
                return [f for f in output.strip().split("\n") if f]
            return []

        except Exception:
            return []
