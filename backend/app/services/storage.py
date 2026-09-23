"""Supabase Storage uploads (service role key; buckets are public-read)."""
import uuid

import httpx

from app.config import settings


async def upload_photo(bucket: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Upload bytes under a random name and return the public URL."""
    path = f"{uuid.uuid4()}.jpg"
    # retries=3: re-attempt failed connections (DNS/network blips); safe because the path is unique
    async with httpx.AsyncClient(timeout=30, transport=httpx.AsyncHTTPTransport(retries=3)) as client:
        res = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{bucket}/{path}",
            content=data,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
                "Content-Type": content_type,
            },
        )
        res.raise_for_status()
    return public_url(bucket, path)


def public_url(bucket: str, path: str) -> str:
    return f"{settings.supabase_url}/storage/v1/object/public/{bucket}/{path}"
