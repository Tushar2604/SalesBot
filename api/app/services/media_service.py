"""Media storage for Content Studio, on the S3/MinIO bucket already deployed.

No new storage provider: `S3_*` settings, the `boto3` dependency and a MinIO
service were already part of this stack and simply had no code behind them.

Two rules shape this module:

* **The bucket stays private.** Objects are read back through short-lived
  presigned URLs, so a leaked key in a preview does not become a permanent
  public link to a customer's unpublished creative.
* **Keys are tenant-prefixed** (`workspaces/{workspace_id}/media/...`), so even
  a mis-scoped listing cannot cross a workspace boundary.

boto3 is synchronous, so every call is pushed to a worker thread rather than
blocking the event loop.
"""

from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from typing import Any

import anyio
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import NotFoundError, UpstreamError, ValidationFailedError
from app.core.logging import get_logger
from app.deps import WorkspaceContext
from app.models.content import MediaAsset, MediaKind

log = get_logger(__name__)

MB = 1024 * 1024

# Limits stated by LinkedIn's documented upload APIs. They are enforced here so a
# file that LinkedIn would reject is refused while the user is still looking at
# the composer, not hours later inside a scheduled publish.
IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
}
VIDEO_TYPES: dict[str, str] = {"video/mp4": ".mp4"}
DOCUMENT_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

MAX_IMAGE_BYTES = 10 * MB
# Below LinkedIn's own 500 MB ceiling on purpose: the publish worker holds the
# file in memory to stream it upstream, and a half-gigabyte buffer per worker is
# not a trade worth making. Raising this means streaming the upload instead.
MAX_VIDEO_BYTES = 200 * MB
MAX_DOCUMENT_BYTES = 100 * MB

# A post carries either one video, one document, or up to 20 images.
MAX_IMAGES_PER_POST = 20

PRESIGN_TTL_SECONDS = 60 * 60


def kind_for(content_type: str) -> MediaKind:
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type in IMAGE_TYPES:
        return MediaKind.IMAGE
    if content_type in VIDEO_TYPES:
        return MediaKind.VIDEO
    if content_type in DOCUMENT_TYPES:
        return MediaKind.DOCUMENT
    raise ValidationFailedError(
        f"“{content_type or 'unknown'}” is not a file type LinkedIn accepts. "
        "Use a JPG, PNG or GIF image, an MP4 video, or a PDF/DOC/PPT document."
    )


def max_bytes_for(kind: MediaKind) -> int:
    return {
        MediaKind.IMAGE: MAX_IMAGE_BYTES,
        MediaKind.VIDEO: MAX_VIDEO_BYTES,
        MediaKind.DOCUMENT: MAX_DOCUMENT_BYTES,
    }[kind]


def limits() -> dict[str, Any]:
    """The client renders these rather than hardcoding its own copy."""
    return {
        "image": {
            "content_types": sorted(IMAGE_TYPES),
            "max_bytes": MAX_IMAGE_BYTES,
            "max_per_post": MAX_IMAGES_PER_POST,
        },
        "video": {
            "content_types": sorted(VIDEO_TYPES),
            "max_bytes": MAX_VIDEO_BYTES,
            "max_per_post": 1,
        },
        "document": {
            "content_types": sorted(DOCUMENT_TYPES),
            "max_bytes": MAX_DOCUMENT_BYTES,
            "max_per_post": 1,
        },
        "max_commentary_chars": 3000,
    }


# ── S3 plumbing ──────────────────────────────────────────────────────────────

_client: Any = None


def _s3() -> Any:
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _client


def _ensure_bucket_sync() -> None:
    """Creates the bucket on first use. MinIO starts with none."""
    client = _s3()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        try:
            client.create_bucket(Bucket=settings.s3_bucket)
        except ClientError as exc:  # already created by a racing request
            if exc.response.get("Error", {}).get("Code") not in (
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            ):
                raise


def _put_sync(key: str, body: bytes, content_type: str) -> None:
    _ensure_bucket_sync()
    _s3().put_object(
        Bucket=settings.s3_bucket, Key=key, Body=body, ContentType=content_type
    )


def _get_sync(key: str) -> bytes:
    response = _s3().get_object(Bucket=settings.s3_bucket, Key=key)
    data: bytes = response["Body"].read()
    return data


def _delete_sync(key: str) -> None:
    _s3().delete_object(Bucket=settings.s3_bucket, Key=key)


def _presign_sync(key: str, ttl: int) -> str:
    url: str = _s3().generate_presigned_url(
        "get_object", Params={"Bucket": settings.s3_bucket, "Key": key}, ExpiresIn=ttl
    )
    return url


def download_sync(asset: MediaAsset) -> bytes:
    """Worker-side read. Used by the publish task to stream bytes to LinkedIn."""
    return _get_sync(asset.storage_key)


def presigned_url_sync(asset: MediaAsset, *, ttl: int = PRESIGN_TTL_SECONDS) -> str:
    try:
        return _presign_sync(asset.storage_key, ttl)
    except (BotoCoreError, ClientError):
        # A preview that cannot be signed is a degraded thumbnail, never a
        # failed request — the post itself is unaffected.
        log.warning("media.presign_failed", storage_key=asset.storage_key)
        return ""


# ── operations ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class StoredMedia:
    asset: MediaAsset
    url: str


def _dimensions(kind: MediaKind, data: bytes) -> tuple[int, int]:
    """Pixel size for the formats whose headers are cheap to parse.

    Deliberately header-only, with no imaging dependency: the value is used for
    preview aspect ratios, and an unknown size simply renders at the default.
    """
    try:
        if kind is not MediaKind.IMAGE:
            return 0, 0
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:3] == b"GIF" and len(data) >= 10:
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        if data[:2] == b"\xff\xd8":  # JPEG: walk the segment markers
            index = 2
            while index + 9 < len(data):
                if data[index] != 0xFF:
                    break
                marker = data[index + 1]
                length = int.from_bytes(data[index + 2 : index + 4], "big")
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    height = int.from_bytes(data[index + 5 : index + 7], "big")
                    width = int.from_bytes(data[index + 7 : index + 9], "big")
                    return width, height
                index += 2 + length
    except (IndexError, ValueError):
        pass
    return 0, 0


async def upload(db: AsyncSession, ctx: WorkspaceContext, file: UploadFile) -> StoredMedia:
    """Validates, stores, and records one uploaded file."""
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not content_type:
        content_type = mimetypes.guess_type(file.filename or "")[0] or ""
    kind = kind_for(content_type)

    data = await file.read()
    if not data:
        raise ValidationFailedError("that file is empty")

    ceiling = max_bytes_for(kind)
    if len(data) > ceiling:
        raise ValidationFailedError(
            f"that {kind.value} is {len(data) / MB:.1f} MB; LinkedIn accepts up to "
            f"{ceiling // MB} MB"
        )

    extension = (
        IMAGE_TYPES.get(content_type)
        or VIDEO_TYPES.get(content_type)
        or DOCUMENT_TYPES.get(content_type)
        or ""
    )
    key = f"workspaces/{ctx.workspace_id}/media/{uuid.uuid4().hex}{extension}"

    try:
        await anyio.to_thread.run_sync(_put_sync, key, data, content_type)
    except (BotoCoreError, ClientError) as exc:
        log.error("media.upload_failed", workspace_id=str(ctx.workspace_id), error=str(exc))
        raise UpstreamError("the file could not be stored; try again") from exc

    width, height = _dimensions(kind, data)
    asset = MediaAsset(
        workspace_id=ctx.workspace_id,
        uploaded_by_id=ctx.user.id,
        kind=kind,
        filename=(file.filename or "upload")[:255],
        content_type=content_type,
        size_bytes=len(data),
        storage_key=key,
        width=width,
        height=height,
    )
    db.add(asset)
    await db.flush()

    url = await anyio.to_thread.run_sync(_presign_sync, key, PRESIGN_TTL_SECONDS)
    return StoredMedia(asset=asset, url=url)


async def get_assets(
    db: AsyncSession, workspace_id: uuid.UUID, asset_ids: list[uuid.UUID]
) -> list[MediaAsset]:
    """Loads assets, refusing any that belong to another workspace."""
    if not asset_ids:
        return []
    rows = (
        (
            await db.execute(
                select(MediaAsset).where(
                    MediaAsset.id.in_(asset_ids), MediaAsset.workspace_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    found = {row.id: row for row in rows}
    missing = [str(a) for a in asset_ids if a not in found]
    if missing:
        raise NotFoundError("one of those uploads no longer exists")
    # Preserve the caller's ordering — it is the post's display order.
    return [found[a] for a in asset_ids]


def validate_attachment_set(assets: list[MediaAsset]) -> None:
    """Enforces what LinkedIn allows to be attached to a single post."""
    if not assets:
        return

    kinds = {asset.kind for asset in assets}
    if len(kinds) > 1:
        raise ValidationFailedError(
            "a LinkedIn post can carry images, or one video, or one document — not a mix"
        )

    kind = next(iter(kinds))
    if kind is MediaKind.IMAGE and len(assets) > MAX_IMAGES_PER_POST:
        raise ValidationFailedError(
            f"a LinkedIn post can carry up to {MAX_IMAGES_PER_POST} images"
        )
    if kind in (MediaKind.VIDEO, MediaKind.DOCUMENT) and len(assets) > 1:
        raise ValidationFailedError(f"a LinkedIn post can carry only one {kind.value}")


async def presign(asset: MediaAsset, *, ttl: int = PRESIGN_TTL_SECONDS) -> str:
    try:
        return await anyio.to_thread.run_sync(_presign_sync, asset.storage_key, ttl)
    except (BotoCoreError, ClientError):
        log.warning("media.presign_failed", storage_key=asset.storage_key)
        return ""


async def delete(db: AsyncSession, ctx: WorkspaceContext, asset_id: uuid.UUID) -> None:
    asset = await db.get(MediaAsset, asset_id)
    if asset is None or asset.workspace_id != ctx.workspace_id:
        raise NotFoundError("upload not found")

    key = asset.storage_key
    await db.delete(asset)
    try:
        await anyio.to_thread.run_sync(_delete_sync, key)
    except (BotoCoreError, ClientError):
        # The row is gone either way; an orphaned object is a storage-lifecycle
        # concern, not a user-facing failure.
        log.warning("media.delete_failed", storage_key=key)
