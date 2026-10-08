"""The raster layers of a project (phase 41, decision D315): what a habitat run may name
(`GET /projects/{id}/analysis-layers`: the provider's layers, a distance per feature type,
the uploads) and the uploads themselves, GeoTIFFs kept in the analysis layers bucket with
what their header says. The header is read here without a raster library
(`shared/analysis/geotiff.py`), so a file without a CRS is refused at once; the pixels are
the worker's business."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import flush_or_409
from protect_api.deps import ProjectContext, require_permission
from protect_api.schemas.analysis import LayerChoiceRead, ProjectLayerRead
from shared.analysis.geotiff import GeoTiffError, read_geotiff_header
from shared.analysis.rasters import (
    DISTANCE_PREFIX,
    FETCHED_LAYERS,
    layer_key,
    project_layers,
)
from shared.config import get_settings
from shared.database import get_session
from shared.enums import LayerKind
from shared.models import ProjectLayer
from shared.permissions import Permission
from shared.storage import put_object, remove_object

router = APIRouter(tags=["analysis layers"])

#: A band name: what the form shows and the model's term is called after; a predictor name
#: hrHSA writes into its design matrix, so letters, digits and underscores only.
NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
#: A geographic layer's pixel in degrees becomes metres at the equator for the record.
M_PER_DEGREE = 111_320.0


@router.get("/projects/{project_id}/analysis-layers", response_model=list[LayerChoiceRead])
async def list_layer_choices(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[LayerChoiceRead]:
    """Every layer a habitat run of the project may name, in the order the form offers them."""
    choices = await project_layers(session, context.project.id)
    return [LayerChoiceRead(**c.document()) for c in choices]


@router.get("/projects/{project_id}/layers", response_model=list[ProjectLayerRead])
async def list_project_layers(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectLayer]:
    rows = await session.scalars(
        select(ProjectLayer)
        .where(ProjectLayer.project_id == context.project.id)
        .order_by(ProjectLayer.name)
    )
    return list(rows.all())


@router.post(
    "/projects/{project_id}/layers",
    response_model=ProjectLayerRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_layer(
    file: UploadFile,
    name: str = Query(min_length=1, max_length=64, description="The band name, a-z, 0-9, _"),
    label: str = Query(min_length=1, max_length=200),
    kind: LayerKind = Query(default=LayerKind.CONTINUOUS),
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ProjectLayer:
    """Upload a GeoTIFF as a covariate layer of the project. The file must carry a CRS with an
    EPSG code, be north-up, and sit within the size bound; its name must not be one of the
    provider's or a distance layer's."""
    settings = get_settings()
    if not NAME.match(name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The name is the band name: lower-case letters, digits and underscores, starting "
            "with a letter",
        )
    if name in FETCHED_LAYERS or name.startswith(DISTANCE_PREFIX):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{name} is the name of a layer Protect makes itself; choose another",
        )
    data = await file.read(settings.layer_max_bytes + 1)
    if len(data) > settings.layer_max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"The file exceeds {settings.layer_max_bytes} bytes"
        )
    try:
        header = read_geotiff_header(data)
    except GeoTiffError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if header.bands != 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The file has {header.bands} bands; a layer is one band",
        )
    pixel_m = header.pixel_x * (M_PER_DEGREE if header.geographic else 1.0)
    row = ProjectLayer(
        project_id=context.project.id,
        name=name,
        label=label,
        kind=kind,
        object_key="",
        size_bytes=len(data),
        epsg=header.epsg,
        width=header.width,
        height=header.height,
        pixel_m=pixel_m,
        extent={
            "west": header.extent[0],
            "south": header.extent[1],
            "east": header.extent[2],
            "north": header.extent[3],
        },
        nodata=header.nodata,
        created_by_user_id=context.user.id,
    )
    session.add(row)
    await flush_or_409(session, "layer")
    row.object_key = layer_key(context.project.id, row.id)
    await put_object(settings.minio_bucket_analysis_layers, row.object_key, data, "image/tiff")
    await record_audit(
        session,
        user=context.user,
        action="layer.uploaded",
        object_type="project_layer",
        object_id=str(row.id),
        project_id=context.project.id,
        details={
            "name": name,
            "filename": file.filename or "",
            "bytes": len(data),
            "epsg": header.epsg,
            "cells": header.cells,
        },
    )
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/projects/{project_id}/layers/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_layer(
    layer_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.scalar(
        select(ProjectLayer).where(
            ProjectLayer.id == layer_id, ProjectLayer.project_id == context.project.id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such layer")
    key = row.object_key
    await record_audit(
        session,
        user=context.user,
        action="layer.deleted",
        object_type="project_layer",
        object_id=str(row.id),
        project_id=context.project.id,
        details={"name": row.name},
    )
    await session.delete(row)
    await session.commit()
    await remove_object(get_settings().minio_bucket_analysis_layers, key)
