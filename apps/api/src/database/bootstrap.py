"""There is still a single 'default' tenant row (seeded by the initial
migration) — `users.tenant_id` makes that real instead of implicit, but
every logged-in user shares it for now. Real multi-tenant isolation (more
than one Tenant row, cross-tenant access checks) is still not built.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import SrsProject, Tenant


async def get_default_tenant(db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise RuntimeError("default tenant missing — did the initial migration run?")
    return tenant


async def get_or_create_srs_project(
    db: AsyncSession,
    *,
    tenant_id,
    azure_org: str,
    azure_project: str,
    azure_base_url: str,
    created_by_user_id: uuid.UUID | None = None,
) -> SrsProject:
    result = await db.execute(
        select(SrsProject).where(
            SrsProject.tenant_id == tenant_id,
            SrsProject.azure_org == azure_org,
            SrsProject.azure_project == azure_project,
        )
    )
    project = result.scalar_one_or_none()
    if project is not None:
        return project

    project = SrsProject(
        tenant_id=tenant_id,
        name=f"{azure_org}/{azure_project}",
        azure_org=azure_org,
        azure_project=azure_project,
        azure_base_url=azure_base_url,
        created_by_user_id=created_by_user_id,
    )
    db.add(project)
    await db.flush()
    return project
