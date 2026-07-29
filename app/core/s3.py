import logging
import hashlib
import asyncio
import boto3
from botocore.exceptions import ClientError
from typing import Tuple, Optional
from fastapi import HTTPException

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class S3StorageService:
    def __init__(self):
        if not all([settings.aws_region, settings.aws_access_key_id, settings.aws_secret_access_key, settings.aws_s3_bucket]):
            logger.warning("AWS S3 credentials are not fully configured in environment.")
            self.client = None
            return
            
        try:
            self.client = boto3.client(
                's3',
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key
            )
            # Parse bucket name and default prefix if a slash is provided (e.g., gramosoft/grag)
            bucket_parts = settings.aws_s3_bucket.split('/', 1)
            self.bucket_name = bucket_parts[0]
            self.base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            self.client = None

    def _store_file_sync(self, tenant_id: str, filename: str, file_bytes: bytes) -> Tuple[bool, Optional[str]]:
        """
        Synchronous method to check for duplicates and upload to S3.
        Returns (is_duplicate: bool, error_message: str|None)
        """
        if not self.client:
            logger.error("S3 client not initialized. Cannot store file.")
            raise ValueError("S3 configuration is missing or invalid.")

        # Compute SHA-256 hash of the file
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        
        # Construct S3 key using the original filename
        s3_key = f"{self.base_prefix}uploads/{tenant_id}/{filename}"
        
        # Check if the file already exists (duplicate detection based on exact filename)
        try:
            response = self.client.head_object(Bucket=self.bucket_name, Key=s3_key)
            # If we succeed, an object with this filename exists. 
            # Let's check if it's the exact same content (duplicate)
            existing_hash = response.get('Metadata', {}).get('content-hash')
            if existing_hash == file_hash:
                logger.info(f"Duplicate file detected for tenant {tenant_id}: {filename} (Hash: {file_hash})")
                return True, None
            else:
                # Same filename, different content. We will overwrite it or append a timestamp.
                # For simplicity, we'll allow it to be overwritten (which behaves like an update).
                pass
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code in ['404', '403']:
                # File doesn't exist (404) or IAM lacks list permissions (403), proceed to upload
                pass
            else:
                logger.error(f"Error checking S3 object existence: {e}")
                raise e

        # Upload the new file
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_bytes,
                Metadata={
                    'original-filename': filename.encode('utf-8', 'ignore').decode('utf-8'),
                    'content-hash': file_hash
                }
            )
            logger.info(f"Successfully uploaded {filename} to S3 bucket {self.bucket_name} at key {s3_key}")
            return False, None
        except Exception as e:
            logger.error(f"Failed to upload file to S3: {e}")
            return False, str(e)

    async def store_file_if_not_duplicate(self, tenant_id: str, filename: str, file_bytes: bytes) -> None:
        """
        Asynchronously checks for duplicates and stores the file in S3.
        If a duplicate is detected (same file exists in S3), it proceeds gracefully
        to allow importing/linking the file to other agents or retrying.
        """
        if not self.client:
            # If S3 is not configured, we might want to skip or raise error. 
            # Given the requirement, S3 storage is mandatory for user uploads.
            raise HTTPException(status_code=500, detail="S3 storage is not configured properly on the server.")

        try:
            is_duplicate, error_msg = await asyncio.to_thread(
                self._store_file_sync, str(tenant_id), filename, file_bytes
            )
            
            if is_duplicate:
                logger.info(f"Duplicate file detected in S3 for tenant {tenant_id}: {filename}. Skipping upload and proceeding gracefully.")
                return
            
            if error_msg:
                raise HTTPException(status_code=500, detail=f"Failed to store file in S3: {error_msg}")
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in S3 storage service: {e}")
            raise HTTPException(status_code=500, detail="An error occurred while communicating with AWS S3.")

    def get_s3_url(self, tenant_id: str, filename: str) -> str:
        """
        Determines the public/presigned standard S3 URL for a given tenant's filename.
        """
        bucket_val = settings.aws_s3_bucket or "default-bucket"
        bucket_parts = bucket_val.split('/', 1)
        bucket_name = bucket_parts[0]
        base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
        s3_key = f"{base_prefix}uploads/{tenant_id}/{filename}"
        region = settings.aws_region or "us-east-1"
        return f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"

    def get_file_stream(self, s3_key: str):
        """
        Returns a streaming body for the file stored in S3.
        """
        if not self.client:
            logger.error("S3 client not initialized. Cannot stream file.")
            raise ValueError("S3 configuration is missing or invalid.")
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=s3_key)
            return response['Body']
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            logger.error(f"S3 get_object error for key {s3_key}: {e}")
            raise e

    def store_parsed_content(self, tenant_id: str, kb_id: str, content: str, content_type: str = "text/plain") -> str:
        """
        Stores the extracted text in S3 and returns the full path/URL.
        Key: parsed/{tenant_id}/{kb_id}/content.txt or content.html
        """
        if not self.client:
            logger.error("S3 client not initialized. Cannot store parsed content.")
            raise ValueError("S3 configuration is missing or invalid.")
        
        # s3_key structure: parsed/{tenant_id}/{kb_id}/content.txt or content.html
        bucket_val = settings.aws_s3_bucket or "default-bucket"
        bucket_parts = bucket_val.split('/', 1)
        base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
        
        if content_type == "text/html":
            ext = "html"
        elif "markdown" in content_type:
            ext = "md"
        else:
            ext = "txt"
        s3_key = f"{base_prefix}parsed/{tenant_id}/{kb_id}/content.{ext}"
        
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType=content_type
            )
            logger.info(f"Successfully uploaded parsed content to S3 at key {s3_key} with ContentType {content_type}")
            
            # Return the full URL/path
            bucket_name = bucket_parts[0]
            region = settings.aws_region or "us-east-1"
            return f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
        except Exception as e:
            logger.error(f"Failed to upload parsed content to S3: {e}")
            raise e

    def _parse_s3_key_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        if ".amazonaws.com/" in url:
            return url.split(".amazonaws.com/", 1)[1]
        try:
            parts = url.split("/", 3)
            if len(parts) >= 4:
                return parts[3]
        except Exception:
            pass
        return None

    async def delete_file_by_url(self, url: str) -> bool:
        """
        Asynchronously deletes an object from S3 using its URL.
        """
        if not self.client or not url:
            return False
            
        key = self._parse_s3_key_from_url(url)
        if not key:
            logger.warning(f"Could not parse S3 key from URL: {url}")
            return False
            
        def _delete():
            try:
                self.client.delete_object(Bucket=self.bucket_name, Key=key)
                logger.info(f"Successfully deleted key {key} from S3 bucket {self.bucket_name}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete S3 key {key}: {e}")
                return False
                
        return await asyncio.to_thread(_delete)



