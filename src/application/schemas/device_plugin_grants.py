"""Wire contracts shared by device package approval and operation admission."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

Operation = Literal["install", "invoke"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Capability = Annotated[str, Field(min_length=1, max_length=128)]


class DevicePackageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: Identifier
    generation_id: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{64}|p[0-9a-f]{63})$")]
    bundle_digest: Digest
    approved_permissions: list[Capability] = Field(max_length=128)


class DevicePackageApproval(DevicePackageBinding):
    user_id: Identifier
    device_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    permissions: list[Operation] = Field(min_length=1, max_length=2)
    expires_at: AwareDatetime


class DevicePackageCheck(DevicePackageBinding):
    device_proof: SecretStr = Field(min_length=43, max_length=43)
    permission: Operation
    grant_id: Annotated[str, Field(max_length=36)] | None = None


class DeviceGrantView(DevicePackageBinding):
    grant_id: str
    user_id: str
    tenant_id: str
    project_id: str
    device_fingerprint: str
    permissions: list[Operation]
    expires_at: AwareDatetime


class DeviceAdmissionView(DevicePackageBinding):
    allowed: Literal[True] = True
    grant_id: str
    user_id: str
    tenant_id: str
    project_id: str
    permission: Operation
