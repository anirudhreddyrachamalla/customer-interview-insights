"""Azure Blob Storage backend for audio + transcript persistence.

Public surface used by :mod:`app.services.audio` and the pipeline:

* :func:`upload_stream` — stream a multipart upload to a blob, enforcing
  an incremental byte cap (mirrors the local-FS path's behavior).
* :func:`get_blob_size` — fetch the blob's content-length.
* :func:`iter_blob_range` — async generator yielding inclusive byte ranges.
* :func:`download_to_tempfile` — materialize a blob to a local temp file
  (needed for tinytag duration probes and the AssemblyAI / VTT-parser
  call sites that take a filesystem path).

Authentication is via :class:`azure.identity.aio.DefaultAzureCredential`,
which picks up the App Service managed identity in production and falls
back to ``az login`` / env vars locally. Container names + account name
come from :class:`app.config.Settings`.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.config import get_settings

logger = logging.getLogger(__name__)

# Streaming chunk size for uploads + range reads (1 MiB).
_CHUNK_SIZE: int = 1024 * 1024


def _account_url() -> str:
    settings = get_settings()
    if not settings.azure_storage_account:
        raise RuntimeError(
            "AZURE_STORAGE_ACCOUNT is not set; cannot use storage_backend='azure_blob'"
        )
    return f"https://{settings.azure_storage_account}.blob.core.windows.net"


def _credential() -> Any:
    # Imported lazily so the local backend doesn't pay the azure-identity
    # import cost (and so dev environments without the package set still
    # boot, though the deployed image always has it).
    from azure.identity.aio import DefaultAzureCredential

    return DefaultAzureCredential()


def _blob_service_client() -> Any:
    from azure.storage.blob.aio import BlobServiceClient

    return BlobServiceClient(account_url=_account_url(), credential=_credential())


async def upload_stream(
    upload: UploadFile,
    *,
    container: str,
    key: str,
    max_bytes: int,
    too_large_exc: type[Exception],
) -> int:
    """Stream a multipart upload to ``container/key``.

    Raises ``too_large_exc(total)`` if the running byte count exceeds
    ``max_bytes``. The blob is deleted on size-cap failure so a partial
    upload never lingers.

    Returns the total number of bytes written.
    """
    total = 0

    async def _iter_chunks() -> AsyncIterator[bytes]:
        nonlocal total
        while True:
            chunk = await upload.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise too_large_exc(total)
            yield chunk

    service = _blob_service_client()
    try:
        blob = service.get_blob_client(container=container, blob=key)
        try:
            await blob.upload_blob(_iter_chunks(), overwrite=True)
        except Exception:
            # Best-effort cleanup of a partial blob (the size-cap path
            # is the common case here).
            try:
                await blob.delete_blob()
            except Exception:  # noqa: BLE001
                logger.warning("failed to delete partial blob %s/%s", container, key)
            raise
    finally:
        await service.close()
        await upload.close()

    return total


async def get_blob_size(container: str, key: str) -> int:
    service = _blob_service_client()
    try:
        blob = service.get_blob_client(container=container, blob=key)
        props = await blob.get_blob_properties()
        return int(props.size)
    finally:
        await service.close()


async def iter_blob_range(
    container: str,
    key: str,
    start: int,
    end: int,
) -> AsyncIterator[bytes]:
    """Yield bytes from ``container/key`` between ``start`` and ``end`` inclusive."""
    length = end - start + 1
    service = _blob_service_client()
    try:
        blob = service.get_blob_client(container=container, blob=key)
        downloader = await blob.download_blob(offset=start, length=length)
        async for chunk in downloader.chunks():
            yield chunk
    finally:
        await service.close()


async def download_to_tempfile(container: str, key: str) -> Path:
    """Download a blob to a unique temp file and return its path.

    Caller owns cleanup (``path.unlink(missing_ok=True)``). Suffix is
    derived from the blob key so tinytag / parsers that sniff by
    extension still work.
    """
    suffix = Path(key).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_name = tmp.name
    dest = Path(tmp_name)

    service = _blob_service_client()
    try:
        blob = service.get_blob_client(container=container, blob=key)
        downloader = await blob.download_blob()
        with dest.open("wb") as fh:
            async for chunk in downloader.chunks():
                fh.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await service.close()

    return dest
