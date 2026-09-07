import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.domain.model.memory.memory import Memory
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.models import Base, Project, Tenant, User
from src.infrastructure.adapters.secondary.sql_memory_repository import SqlAlchemyMemoryRepository


@pytest.fixture
async def db_session():
    # Use in-memory SQLite for testing repository logic
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        session.add_all(
            [
                User(id=user_id, email=f"{user_id}@test.local", hashed_password="unused")
                for user_id in ["user_1", "u1"]
            ]
        )
        await session.flush()
        session.add(Tenant(id="tenant", name="QA", slug="qa", owner_id="user_1"))
        await session.flush()
        for project_id in ["proj_1", "proj_A", "proj_B"]:
            session.add(
                Project(id=project_id, name=project_id, tenant_id="tenant", owner_id="user_1")
            )
            await session.flush()
            session.add(Enrollment(project_id=project_id, tenant_id="tenant", enabled=False))
        await session.commit()
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_save_and_find(db_session):
    # Arrange
    repo = SqlAlchemyMemoryRepository(db_session)
    memory = Memory(
        project_id="proj_1", title="Test Title", content="Test Content", author_id="user_1"
    )

    # Act
    await repo.save(memory)
    found_memory = await repo.find_by_id(memory.id)

    # Assert
    assert found_memory is not None
    assert found_memory.id == memory.id
    assert found_memory.title == "Test Title"
    assert found_memory.content == "Test Content"


@pytest.mark.asyncio
async def test_repository_list_by_project(db_session):
    # Arrange
    repo = SqlAlchemyMemoryRepository(db_session)
    memory1 = Memory(project_id="proj_A", title="Mem 1", content="C1", author_id="u1")
    memory2 = Memory(project_id="proj_A", title="Mem 2", content="C2", author_id="u1")
    memory3 = Memory(project_id="proj_B", title="Mem 3", content="C3", author_id="u1")

    await repo.save(memory1)
    await repo.save(memory2)
    await repo.save(memory3)

    # Act
    results = await repo.list_by_project("proj_A")

    # Assert
    assert len(results) == 2
    titles = [m.title for m in results]
    assert "Mem 1" in titles
    assert "Mem 2" in titles
    assert "Mem 3" not in titles


@pytest.mark.asyncio
async def test_repository_search_by_project(db_session):
    # Arrange
    repo = SqlAlchemyMemoryRepository(db_session)
    memory1 = Memory(project_id="proj_A", title="Alpha Note", content="Plain text", author_id="u1")
    memory2 = Memory(project_id="proj_A", title="Beta", content="Alpha content", author_id="u1")
    memory3 = Memory(
        project_id="proj_B", title="Alpha Note", content="Other project", author_id="u1"
    )

    await repo.save(memory1)
    await repo.save(memory2)
    await repo.save(memory3)

    # Act
    results = await repo.search_by_project("proj_A", "alpha")

    # Assert
    assert {memory.id for memory in results} == {memory1.id, memory2.id}
