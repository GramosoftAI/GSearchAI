import logging
from typing import Dict, Any, List
from app.modules.connectors.google.auth import GoogleAuthManager, execute_google_request, GMAIL_SCOPES
from app.core.database import AsyncSessionLocal
from app.modules.connectors.google.models import GmailSyncState
from sqlalchemy import select

logger = logging.getLogger(__name__)

async def gmail_sync_job(ctx: Dict[Any, Any], kb_id: str, tenant_id: str, user_email: str, label_ids: List[str] = None, credentials: Dict[str, Any] = None):
    from app.core.config import get_settings
    if not getattr(get_settings(), "enable_gmail_connector", False):
        logger.info(f"Gmail connector disabled by feature flag (enable_gmail_connector=False). Skipping gmail_sync_job for {user_email}")
        return {"status": "disabled", "reason": "enable_gmail_connector is False"}

    logger.info(f"Starting gmail_sync_job for {user_email}")
    redis = ctx.get('redis')
    
    auth_manager = GoogleAuthManager()
    if credentials:
        auth_manager.load_credentials(credentials, scopes=GMAIL_SCOPES)
    
    
    async with auth_manager.get_client(user_email) as client:
        # 1. Determine if we have a history_id
        async with AsyncSessionLocal() as db:
            query = select(GmailSyncState).where(GmailSyncState.user_id == user_email)
            res = await db.execute(query)
            sync_state = res.scalar_one_or_none()
            
            # If label_ids are explicitly provided, force a full sync to ensure we capture
            # the baseline for those specific labels (e.g. if the user switched from INBOX to STARRED).
            history_id = sync_state.history_id if sync_state and not label_ids else None
        
        message_ids = []
        new_history_id = None
        
        if history_id:
            # Incremental sync using History API
            logger.info(f"Performing incremental sync from historyId {history_id}")
            params = {"startHistoryId": str(history_id)}
            if label_ids:
                params["labelId"] = label_ids[0] # History API only supports one labelId
                
            page_token = None
            has_more = True
            
            while has_more:
                if page_token:
                    params["pageToken"] = page_token
                
                try:
                    res = await execute_google_request(client, "GET", f"/gmail/v1/users/{user_email}/history", params=params)
                    history_records = res.get("history", [])
                    for record in history_records:
                        if "messagesAdded" in record:
                            for msg_added in record["messagesAdded"]:
                                message_ids.append(msg_added["message"]["id"])
                    
                    new_history_id = res.get("historyId")
                    page_token = res.get("nextPageToken")
                    if not page_token:
                        has_more = False
                except Exception as e:
                    logger.error(f"Incremental sync failed: {e}")
                    # Fallback to full sync
                    history_id = None
                    has_more = False
                    message_ids = []
        
        if not history_id:
            # Full sync using Messages API
            print(f"DEBUG: Performing full sync for {user_email} with label_ids={label_ids}")
            page_token = None
            has_more = True
            
            while has_more:
                params = {"maxResults": 500}
                if label_ids:
                    # If multiple labels are selected, use 'q' parameter with OR logic
                    # because passing multiple labelIds to Gmail API acts as an AND operation
                    if len(label_ids) > 1:
                        params["q"] = " OR ".join([f"label:{label}" for label in label_ids])
                    else:
                        params["labelIds"] = label_ids
                if page_token:
                    params["pageToken"] = page_token
                    
                print(f"DEBUG: Calling execute_google_request with params={params}")
                res = await execute_google_request(client, "GET", f"/gmail/v1/users/{user_email}/messages", params=params)
                
                messages = res.get("messages", [])
                print(f"DEBUG: Google API returned {len(messages)} messages for this page.")
                for msg in messages:
                    message_ids.append(msg["id"])
                    
                page_token = res.get("nextPageToken")
                # For initial sync, get the current profile history ID to save it later
                if not new_history_id:
                    profile_res = await execute_google_request(client, "GET", f"/gmail/v1/users/{user_email}/profile")
                    new_history_id = profile_res.get("historyId")
                    
                if not page_token:
                    has_more = False
                    
        # Remove duplicates
        message_ids = list(set(message_ids))
        logger.info(f"Found {len(message_ids)} messages to process")
        
        # Save new history state
        if new_history_id:
            async with AsyncSessionLocal() as db:
                if sync_state:
                    sync_state.history_id = int(new_history_id)
                else:
                    sync_state = GmailSyncState(user_id=user_email, history_id=int(new_history_id))
                    db.add(sync_state)
                await db.commit()
                
        # Batch messages into groups of 100
        batch_size = 100
        for i in range(0, len(message_ids), batch_size):
            batch = message_ids[i:i + batch_size]
            await redis.enqueue_job(
                'email_processing_job', 
                kb_id, 
                tenant_id, 
                user_email, 
                batch,
                i // batch_size,
                credentials
            )
            logger.info(f"Enqueued email_processing_job batch {i // batch_size} with {len(batch)} messages")
            
    return {"status": "success", "messages_queued": len(message_ids)}
