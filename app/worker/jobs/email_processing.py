import logging
import asyncio
import base64
from typing import Dict, Any, List
from bs4 import BeautifulSoup
import re
from app.modules.connectors.google.auth import GoogleAuthManager, execute_google_request, GMAIL_SCOPES
from app.core.database import AsyncSessionLocal
from app.modules.connectors.google.models import GmailMessage

logger = logging.getLogger(__name__)

def _decode_body(payload: Dict[str, Any]) -> str:
    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get("mimeType") in ("text/plain", "text/html") or "parts" in part:
                body += _decode_body(part)
    elif 'body' in payload and 'data' in payload['body']:
        data = payload['body']['data']
        try:
            data += '=' * (-len(data) % 4)
            body = base64.urlsafe_b64decode(data).decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to decode message body: {e}")
    return body

def clean_email_body(html_body: str) -> str:
    if not html_body:
        return ""
        
    soup = BeautifulSoup(html_body, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style", "meta"]):
        script.extract()
        
    # Remove quoted replies (common Gmail pattern: <div class="gmail_quote">)
    for quote in soup.find_all("div", class_="gmail_quote"):
        quote.extract()
        
    text = soup.get_text(separator=' ')
    
    # Clean whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """Basic character-based chunking to strictly prevent token limits."""
    chunks = []
    if not text:
        return chunks
    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size
    for i in range(0, len(text), step):
        chunk = text[i:i + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks

async def fetch_single_message(client, user_email: str, msg_id: str) -> Dict[str, Any]:
    try:
        res = await execute_google_request(client, "GET", f"/gmail/v1/users/{user_email}/messages/{msg_id}", params={"format": "full"})
        headers = res.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
        date_str = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')
        thread_id = res.get('threadId', '')
        labels = res.get('labelIds', [])
        
        iso_date = date_str
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                iso_date = dt.isoformat()
            except Exception as e:
                logger.warning(f"Could not parse date {date_str}: {e}")
                
        body_text = _decode_body(res.get('payload', {}))
        if not body_text:
            body_text = res.get("snippet", "")
            
        cleaned_body = clean_email_body(body_text)
        
        return {
            "id": msg_id,
            "thread_id": thread_id,
            "subject": subject,
            "sender": sender,
            "date": iso_date,
            "labels": labels,
            "body": cleaned_body
        }
    except Exception as e:
        logger.error(f"Failed to fetch message {msg_id}: {e}")
        return None

async def email_processing_job(ctx: Dict[Any, Any], kb_id: str, tenant_id: str, user_email: str, message_ids: List[str], batch_index: int, credentials: Dict[str, Any] = None):
    from app.core.config import get_settings
    if not getattr(get_settings(), "enable_gmail_connector", False):
        logger.info(f"Gmail connector disabled by feature flag (enable_gmail_connector=False). Skipping email_processing_job for {user_email}")
        return {"status": "disabled", "reason": "enable_gmail_connector is False"}

    logger.info(f"Starting email_processing_job for batch {batch_index} ({len(message_ids)} messages)")
    redis = ctx.get('redis')
    
    auth_manager = GoogleAuthManager()
    if credentials:
        auth_manager.load_credentials(credentials, scopes=GMAIL_SCOPES)
        
    processed_messages = []
    
    async with auth_manager.get_client(user_email) as client:
        # Fetch concurrently (limit concurrency to avoid hammering the API)
        tasks = []
        semaphore = asyncio.Semaphore(10)
        
        async def fetch_with_semaphore(msg_id):
            async with semaphore:
                return await fetch_single_message(client, user_email, msg_id)
                
        for msg_id in message_ids:
            tasks.append(fetch_with_semaphore(msg_id))
            
        results = await asyncio.gather(*tasks)
        processed_messages = [r for r in results if r is not None and r.get('body')]
        
    if not processed_messages:
        logger.info("No messages processed successfully in this batch")
        return {"status": "success", "processed": 0}
        
    from sqlalchemy.dialects.postgresql import insert
    
    # Save to PostgreSQL
    async with AsyncSessionLocal() as db:
        for msg in processed_messages:
            stmt = insert(GmailMessage).values(
                user_id=user_email,
                message_id=msg['id'],
                thread_id=msg['thread_id'],
                subject=msg['subject'],
                sender=msg['sender'],
                body=msg['body'],
                labels=msg['labels'],
                sync_status='processed'
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['message_id'],
                set_={
                    'thread_id': stmt.excluded.thread_id,
                    'subject': stmt.excluded.subject,
                    'sender': stmt.excluded.sender,
                    'body': stmt.excluded.body,
                    'labels': stmt.excluded.labels,
                    'sync_status': stmt.excluded.sync_status
                }
            )
            await db.execute(stmt)
        await db.commit()
        
    # Chunk messages
    chunks_to_embed = []
    for msg in processed_messages:
        text = f"Subject: {msg['subject']}\nFrom: {msg['sender']}\nDate: {msg['date']}\n\n{msg['body']}"
        text_chunks = chunk_text(text, chunk_size=500, overlap=100)
        
        for i, chunk in enumerate(text_chunks):
            chunks_to_embed.append({
                "message_id": msg['id'],
                "thread_id": msg['thread_id'],
                "sender": msg['sender'],
                "subject": msg['subject'],
                "date": msg['date'],
                "chunk_index": i,
                "text": chunk
            })
            
    # Batch embeddings into chunks of 50 to avoid payload limits
    embed_batch_size = 50
    for i in range(0, len(chunks_to_embed), embed_batch_size):
        emb_batch = chunks_to_embed[i:i + embed_batch_size]
        await redis.enqueue_job(
            'embedding_job',
            kb_id,
            tenant_id,
            emb_batch
        )
        
    return {"status": "success", "processed": len(processed_messages), "chunks": len(chunks_to_embed)}
