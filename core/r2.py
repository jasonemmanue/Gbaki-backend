"""
core/r2.py — accès Cloudflare R2 (compatible S3), partagé par les vues et les commandes.
"""
import boto3
from botocore.config import Config
from django.conf import settings


def r2_configured() -> bool:
    return bool(settings.CF_R2_ENDPOINT_URL and settings.CF_R2_ACCESS_KEY)


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.CF_R2_ENDPOINT_URL,
        aws_access_key_id=settings.CF_R2_ACCESS_KEY,
        aws_secret_access_key=settings.CF_R2_SECRET_KEY,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
        region_name="auto",
    )


def generate_presigned_url(file_path: str, file_name: str = '', force_download: bool = False) -> str:
    """
    Retourne une URL signée R2 valable CF_R2_PRESIGN_EXPIRY secondes.
    Si les credentials R2 ne sont pas configurés, retourne file_path directement.
    """
    if not r2_configured():
        return file_path

    params = {"Bucket": settings.CF_R2_BUCKET_NAME, "Key": file_path}
    if force_download:
        params["ResponseContentDisposition"] = f'attachment; filename="{file_name}"'

    return get_r2_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=settings.CF_R2_PRESIGN_EXPIRY,
    )


def list_objects(prefix: str = '', client=None):
    """Itère sur (clé, taille) de tous les objets sous un préfixe."""
    client = client or get_r2_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.CF_R2_BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]
