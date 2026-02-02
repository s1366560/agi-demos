"""SQL Attachment Repository - SQLAlchemy implementation of AttachmentRepositoryPort."""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.attachment import (
    Attachment,
    AttachmentMetadata,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.domain.ports.repositories.attachment_repository import AttachmentRepositoryPort
from src.infrastructure.adapters.secondary.persistence.attachment_model import AttachmentModel

logger = logging.getLogger(__name__)


class SqlAlchemyAttachmentRepository(AttachmentRepositoryPort):
    """SQLAlchemy implementation of AttachmentRepositoryPort."""

    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self._session = session

    def _to_entity(self, model: AttachmentModel) -> Attachment:
        """Convert database model to domain entity."""
        return Attachment(
            id=model.id,
            conversation_id=model.conversation_id,
            project_id=model.project_id,
            tenant_id=model.tenant_id,
            filename=model.filename,
            mime_type=model.mime_type,
            size_bytes=model.size_bytes,
            object_key=model.object_key,
            purpose=AttachmentPurpose(model.purpose),
            status=AttachmentStatus(model.status),
            upload_id=model.upload_id,
            total_parts=model.total_parts,
            uploaded_parts=model.uploaded_parts or 0,
            sandbox_path=model.sandbox_path,
            metadata=AttachmentMetadata.from_dict(model.file_metadata),
            created_at=model.created_at,
            expires_at=model.expires_at,
            error_message=model.error_message,
        )

    def _to_model_dict(self, entity: Attachment) -> dict:
        """Convert domain entity to model dictionary for insert/update."""
        return {
            "id": entity.id,
            "conversation_id": entity.conversation_id,
            "project_id": entity.project_id,
            "tenant_id": entity.tenant_id,
            "filename": entity.filename,
            "mime_type": entity.mime_type,
            "size_bytes": entity.size_bytes,
            "object_key": entity.object_key,
            "purpose": entity.purpose.value,
            "status": entity.status.value,
            "upload_id": entity.upload_id,
            "total_parts": entity.total_parts,
            "uploaded_parts": entity.uploaded_parts,
            "sandbox_path": entity.sandbox_path,
            "file_metadata": entity.metadata.to_dict() if entity.metadata else {},
            "created_at": entity.created_at,
            "expires_at": entity.expires_at,
            "error_message": entity.error_message,
        }

    async def save(self, attachment: Attachment) -> None:
        """Save an attachment to the repository."""
        try:
            # Check if exists
            result = await self._session.execute(
                select(AttachmentModel).where(AttachmentModel.id == attachment.id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                model_dict = self._to_model_dict(attachment)
                for key, value in model_dict.items():
                    if key != "id":
                        setattr(existing, key, value)
            else:
                # Create new
                model = AttachmentModel(**self._to_model_dict(attachment))
                self._session.add(model)

            await self._session.commit()
            logger.debug(f"Saved attachment: {attachment.id}")

        except Exception as e:
            await self._session.rollback()
            logger.error(f"Failed to save attachment {attachment.id}: {e}")
            raise

    async def get(self, attachment_id: str) -> Optional[Attachment]:
        """Get an attachment by ID."""
        result = await self._session.execute(
            select(AttachmentModel).where(AttachmentModel.id == attachment_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_conversation(
        self,
        conversation_id: str,
        status: Optional[AttachmentStatus] = None,
    ) -> List[Attachment]:
        """Get all attachments for a conversation."""
        query = select(AttachmentModel).where(
            AttachmentModel.conversation_id == conversation_id
        )
        if status:
            query = query.where(AttachmentModel.status == status.value)
        query = query.order_by(AttachmentModel.created_at)

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def get_by_ids(self, attachment_ids: List[str]) -> List[Attachment]:
        """Get multiple attachments by their IDs."""
        if not attachment_ids:
            return []

        result = await self._session.execute(
            select(AttachmentModel).where(AttachmentModel.id.in_(attachment_ids))
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def delete(self, attachment_id: str) -> bool:
        """Delete an attachment."""
        result = await self._session.execute(
            delete(AttachmentModel).where(AttachmentModel.id == attachment_id)
        )
        await self._session.commit()
        deleted = result.rowcount > 0
        if deleted:
            logger.debug(f"Deleted attachment: {attachment_id}")
        return deleted

    async def delete_expired(self) -> int:
        """Delete all expired attachments."""
        now = datetime.utcnow()
        result = await self._session.execute(
            delete(AttachmentModel).where(
                AttachmentModel.expires_at.isnot(None),
                AttachmentModel.expires_at < now,
            )
        )
        await self._session.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Deleted {count} expired attachments")
        return count

    async def update_status(
        self,
        attachment_id: str,
        status: AttachmentStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update the status of an attachment."""
        update_values = {"status": status.value}
        if error_message is not None:
            update_values["error_message"] = error_message

        result = await self._session.execute(
            update(AttachmentModel)
            .where(AttachmentModel.id == attachment_id)
            .values(**update_values)
        )
        await self._session.commit()
        return result.rowcount > 0

    async def update_upload_progress(
        self,
        attachment_id: str,
        uploaded_parts: int,
    ) -> bool:
        """Update the multipart upload progress."""
        result = await self._session.execute(
            update(AttachmentModel)
            .where(AttachmentModel.id == attachment_id)
            .values(uploaded_parts=uploaded_parts)
        )
        await self._session.commit()
        return result.rowcount > 0

    async def update_sandbox_path(
        self,
        attachment_id: str,
        sandbox_path: str,
    ) -> bool:
        """Update the sandbox path after import."""
        result = await self._session.execute(
            update(AttachmentModel)
            .where(AttachmentModel.id == attachment_id)
            .values(sandbox_path=sandbox_path, status=AttachmentStatus.READY.value)
        )
        await self._session.commit()
        return result.rowcount > 0
