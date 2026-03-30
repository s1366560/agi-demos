from __future__ import annotations

from pydantic import BaseModel


class SmtpConfigCreate(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str  # plaintext, will be encrypted by service
    from_email: str
    from_name: str | None = None
    use_tls: bool = True


class SmtpConfigResponse(BaseModel):
    id: str
    tenant_id: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_masked: str  # always masked
    from_email: str
    from_name: str | None = None
    use_tls: bool

    model_config = {"from_attributes": True}


class SmtpTestRequest(BaseModel):
    recipient_email: str
