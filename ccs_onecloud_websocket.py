import asyncio
import json
import logging
import os
import sys
import socket
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import uvicorn
import pickle
from jwt_auth import authenticator
from cloudwatch_logger import CloudWatchLogger
from secret_validator import secret_validator
from elasticache_session_manager import ElastiCacheSessionManager
from dotenv import load_dotenv

# Setup logging using the reusable CloudWatch logger class
# No command-line arguments needed:
# - Region is AUTO-DETECTED from EC2 instance metadata
# - Log group name is unique and doesn't need environment suffix
# - Environment for JWT is passed via query parameter in WebSocket URL

# Get hostname for CloudWatch service name
log_hostname = socket.gethostname()
ip_addr_log = socket.gethostbyname(log_hostname)  # Get the IP address of the current machine based on the hostname

# Initialize CloudWatch logger with modular configuration
# Region will be auto-detected from EC2 metadata
cw_logger = CloudWatchLogger(
    log_group_name='/aws/ec2/ccs-websocket',
    service_name=f'ccs-websocket-{ip_addr_log}',
    log_level=logging.INFO,
    console_logging=False
)

# Get the configured logger
logger = cw_logger.get_logger()

# Load environment variables from .env file
env_file_path = '.env'
if os.path.exists(env_file_path):
    load_dotenv(env_file_path)
    logger.info(f"✅ Loaded environment variables from {env_file_path}")
else:
    logger.warning(f"⚠️  .env file not found at {env_file_path} - SSL will be disabled")

# Add file logging handler
logfile_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # Get the current timestamp formatted as "YYYY-MM-DD_HH-MM-SS"
log_dir = os.getenv('LOG_DIR', '/apps/opt/efs/logs/ccs_onecloud_websocket')  # Get the log directory from environment variables, default to the specified directory if not set
log_filepath = os.path.join(log_dir, f"ccslogs_{ip_addr_log}_{logfile_timestamp}.log")  # Construct the log file path

# Log CloudWatch configuration for debugging
logger.info("🔍 CloudWatch Configuration:")
logger.info(f"   Log Group: {cw_logger.get_log_group_name()}")
logger.info(f"   Log Stream: {cw_logger.get_log_stream_name()}")
logger.info(f"   Region: {cw_logger.region}")
logger.info(f"   CloudWatch Enabled: {cw_logger.is_cloudwatch_enabled()}")
logger.info(f"   Service Name: ccs-websocket-{ip_addr_log}")

# Create log directory if it doesn't exist
os.makedirs(log_dir, exist_ok=True)

# Add file handler to logger
file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

logger.info(f"File logging initialized: {log_filepath}")

# Get port from environment variable with default fallback
server_port = int(os.getenv('PORT', '3003'))

# Log startup configuration to CloudWatch and EFS immediately
logger.info("=" * 60)
logger.info("WebSocket Server Configuration")
logger.info("=" * 60)
logger.info(f"Server Host: 0.0.0.0")
logger.info(f"Server Port: {server_port}")
logger.info(f"Machine IP: {ip_addr_log}")
logger.info(f"CloudWatch Region: {cw_logger.region} (auto-detected)")
logger.info(f"CloudWatch Log Group: /aws/ec2/ccs-websocket")
logger.info(f"CloudWatch Log Stream: {cw_logger.get_log_stream_name()}")
logger.info(f"Log File: {log_filepath}")
logger.info(f"JWT Auth: Use 'env' query parameter (PROD/NONPROD/DEV) in WebSocket URL")
logger.info("Auto-disconnect disabled - sessions remain active until client disconnects")
logger.info("=" * 60)

# Create FastAPI app
app = FastAPI(title="WebSocket Chat Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ElastiCache Session Manager
# Get ElastiCache configuration from environment variables
ELASTICACHE_ENDPOINT = os.getenv('ELASTICACHE_ENDPOINT', 'localhost')  # Dummy default for development
ELASTICACHE_PORT = int(os.getenv('ELASTICACHE_PORT', '6379'))
# Note: ElastiCache password will be fetched from SSM Parameter Store automatically

# Initialize session manager with ElastiCache configuration (password will be auto-fetched from SSM)
session_manager = ElastiCacheSessionManager(
    elasticache_host=ELASTICACHE_ENDPOINT,
    elasticache_port=ELASTICACHE_PORT,
    elasticache_password=None,  # Will be fetched from SSM automatically
    logger=logger  # Pass the main logger instance
)

# Server identification for cross-instance communication
SERVER_ID = f"server_{ip_addr_log}_{server_port}"
logger.info(f"Message forwarding logger started for server {SERVER_ID}")

SERVER_IP = ip_addr_log
SERVER_PORT = server_port

# Log ElastiCache configuration
logger.info("🔧 ElastiCache Configuration:")
logger.info(f"   Endpoint: {ELASTICACHE_ENDPOINT}")
logger.info(f"   Port: {ELASTICACHE_PORT}")
logger.info(f"   Password: {'***' if session_manager.elasticache_password else 'None (will fetch from SSM)'}")
logger.info(f"🏷️  Server Identification:")
logger.info(f"   Server ID: {SERVER_ID}")
logger.info(f"   Server IP: {SERVER_IP}")
logger.info(f"   Server Port: {SERVER_PORT}")

# Legacy in-memory storage (DEPRECATED - keeping for backward compatibility during transition)
# These will be phased out as all operations move to Redis
sessions: Dict[str, WebSocket] = {}
connection_states: Dict[str, bool] = {}
last_ping_time: Dict[str, float] = {}
session_environments: Dict[str, str] = {}
session_tokens: Dict[str, str] = {}
session_secrets: Dict[str, str] = {}
session_uisources: Dict[str, str] = {}

class MessageRequest(BaseModel):
    """Request model for external API messages"""
    session_id: str
    message: str

class FinalMessageRequest(BaseModel):
    """Request model for external API messages"""
    session_id: str
    message: str
    query_id: str
    references: Optional[List[str]] = None

class FeedbackRequest(BaseModel):
    """Request model for feedback API"""
    session_id: str
    vzid: str
    query_id: str
    feedback: str

class InternalEmitRequest(BaseModel):
    """Request model for internal server-to-server communication"""
    session_id: str
    event: str
    data: Dict[str, Any]
class SocketIOEmulator:
    """Emulates Socket.IO events over WebSocket"""
    
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
    
    async def emit(self, event: str, data: Dict[str, Any]):
        """Emit an event to the client"""
        try:
            # Check if WebSocket is still open before sending
            if self.websocket.client_state.value == 1:  # CONNECTED state
                message = {
                    "event": event,
                    "data": data
                }
                await self.websocket.send_text(json.dumps(message))
                logger.debug(f"Sent {event} to client")
            else:
                logger.warning(f"Attempted to send {event} to closed WebSocket connection")
        except Exception as e:
            logger.error(f"Failed to emit {event}: {str(e)}")
            raise  # Re-raise to trigger cleanup

@app.websocket("/ccs/ccs-websocket/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    authorization: Optional[str] = Query(None, alias="Authorization"),
    env: Optional[str] = Query("DEV", alias="env"),
    secret: Optional[str] = Query(None, alias="secret"),
    uisource: Optional[str] = Query(None, alias="uisource")
):
    """
    WebSocket endpoint with JWT or secret-based authentication
    
    Authentication can be provided via query parameters:
    JWT: ws://host/path?Authorization=Bearer%20<token>&env=PROD
    Secret: ws://host/path?secret=<secret>&uisource=slack
    
    Query Parameters:
    - Authorization: Bearer token (required for JWT auth)
    - env: Environment (PROD, NONPROD, DEV) - defaults to DEV
    - secret: Secret key (for non-JWT auth like Slack)
    - uisource: UI source identifier (e.g., 'slack')
    """
    # Generate a unique socket ID for logging
    socket_id = f"socket_{id(websocket)}"
    
    # Determine authentication method based on uisource
    use_secret_auth = uisource and uisource.lower() == "slack"
    token = None
    
    if use_secret_auth:
        # Secret-based authentication for Slack
        if not secret:
            logger.error(f"Connection rejected - No secret provided for {uisource}: {socket_id}")
            await websocket.close(code=1008, reason="Secret required for this UI source")
            return
        
        # Validate secret against AWS SSM Parameter Store
        try:
            is_valid = secret_validator.validate_secret(secret)
            if not is_valid:
                logger.error(f"Connection rejected - Invalid secret for {uisource}: {socket_id}")
                await websocket.close(code=1008, reason="Invalid secret")
                return
            logger.info(f"Secret-based authentication successful for {uisource}: {socket_id}")
        except Exception as e:
            logger.error(f"Connection rejected - Secret validation error for {uisource}: {socket_id} - {str(e)}")
            await websocket.close(code=1008, reason="Secret validation failed")
            return
        
    else:
        # JWT-based authentication (existing logic)
        if not authorization:
            logger.error(f"Connection rejected - No authorization provided: {socket_id}")
            await websocket.close(code=1008, reason="Authorization required")
            return
        
        token = authenticator.extract_token_from_header(authorization)
        if not token:
            logger.error(f"Connection rejected - Invalid authorization format: {socket_id}")
            await websocket.close(code=1008, reason="Invalid authorization format")
            return
        
        # Verify token with the provided environment from query parameter
        decoded = authenticator.verify_jwt_token(token, env)
        if not decoded:
            logger.error(f"Connection rejected - Invalid or expired token for env {env}: {socket_id}")
            await websocket.close(code=1008, reason=f"Invalid or expired token for environment {env}")
            return
    
    # Authentication successful - NOW accept the connection
    await websocket.accept()
    auth_method = "secret" if use_secret_auth else "jwt"
    logger.info(f"Client authenticated and connected: {socket_id} (auth: {auth_method}, env: {env}, uisource: {uisource})")
    
    socket = SocketIOEmulator(websocket)
    current_session_id = None
    session_env = env  # Use the env from query parameter
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            event = message.get("event")
            event_data = message.get("data", {})
            
            if event == "register_session":
                # Use the intendedEnv from registration if provided, otherwise use query param env
                registration_env = event_data.get("intendedEnv") or event_data.get("env", session_env)
                
                # Re-validate token with the specific environment (in case it differs from initial)
                if registration_env != session_env:
                    decoded_env = authenticator.verify_jwt_token(token, registration_env)
                    if not decoded_env:
                        logger.error(f"Registration failed - Token invalid for env {registration_env}: {socket_id}")
                        await websocket.close(code=1008, reason=f"Token invalid for environment {registration_env}")
                        return
                    session_env = registration_env  # Update session env
                
                current_session_id = await handle_register_session(
                    socket, event_data, session_env, token, secret, uisource
                )
                
                if not current_session_id:
                    logger.error(f"Registration failed - Invalid session data: {socket_id}")
                    await websocket.close(code=1011, reason="Registration failed")
                    return
                
            elif event == "chat_request":
                # Must be registered first
                if not current_session_id:
                    logger.error(f"Chat request without registration: {socket_id}")
                    await websocket.close(code=1008, reason="Session not registered")
                    return
                
                # Re-verify authentication for chat request
                session_uisource = await session_manager.get_session_data(current_session_id, "session_uisources")
                if session_uisource and session_uisource.lower() == "slack":
                    # Re-validate secret for Slack sessions
                    session_secret = await session_manager.get_session_data(current_session_id, "session_secrets")
                    try:
                        if not session_secret or not secret_validator.validate_secret(session_secret):
                            logger.error(f"Chat request failed - Invalid secret for session: {current_session_id}")
                            await cleanup_session(current_session_id, websocket)
                            await websocket.close(code=1008, reason="Secret expired or invalid")
                            return
                        logger.info(f"Chat request secret validation successful for session: {current_session_id}")
                    except Exception as e:
                        logger.error(f"Chat request failed - Secret validation error for session {current_session_id}: {str(e)}")
                        await cleanup_session(current_session_id, websocket)
                        await websocket.close(code=1008, reason="Secret validation failed")
                        return
                else:
                    # Re-verify JWT token
                    decoded_chat = authenticator.verify_jwt_token(token, session_env)
                    if not decoded_chat:
                        logger.error(f"Chat request failed - Token expired: {current_session_id}")
                        await cleanup_session(current_session_id, websocket)
                        await websocket.close(code=1008, reason="Token expired")
                        return
                
                await handle_chat_request(socket, event_data)
                
            elif event == "ping":
                # Must be registered to ping
                if not current_session_id:
                    logger.error(f"Ping without registration: {socket_id}")
                    await websocket.close(code=1008, reason="Session not registered")
                    return
                
                await handle_ping(socket, event_data)
                
            else:
                logger.warning(f"Unknown event received: {event} from {socket_id}")
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {socket_id}")
        await cleanup_session(current_session_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for {socket_id}: {str(e)}")
        await cleanup_session(current_session_id, websocket)

async def cleanup_session(session_id: Optional[str], websocket: WebSocket):
    """Clean up session data when connection is lost"""
    # Remove session when client disconnects
    session_to_remove = session_id
    
    if not session_to_remove:
        # Find session by websocket if session_id not provided
        for sid, session_socket in sessions.items():
            if session_socket == websocket:
                session_to_remove = sid
                break
    
    if session_to_remove:
        # Use the session manager's comprehensive cleanup method
        await session_manager.cleanup_session(session_to_remove)
        
        # Legacy cleanup (for backward compatibility during transition)
        sessions.pop(session_to_remove, None)
        connection_states.pop(session_to_remove, None)
        last_ping_time.pop(session_to_remove, None)
        session_environments.pop(session_to_remove, None)
        session_tokens.pop(session_to_remove, None)
        session_secrets.pop(session_to_remove, None)
        session_uisources.pop(session_to_remove, None)




async def forward_to_server_with_websocket(session_id: str, event: str, data: Dict[str, Any], server_info: dict):
    """Forward message to the server that has the actual WebSocket object"""
    logger.info(f"=== FORWARDING START - Session: {session_id}, Event: {event} ===")
    logger.info(f"Target: {server_info.get('server_id', 'UNKNOWN')} ({server_info.get('server_ip', 'UNKNOWN')}:{server_info.get('server_port', 'UNKNOWN')})")
    
    try:
        target_url = f"https://{server_info['server_ip']}:{server_info['server_port']}/ccs/ccs-websocket/api/internal/emit"
        payload = {
            "session_id": session_id,
            "event": event,
            "data": data
        }
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(target_url, json=payload)
            
            if response.status_code == 200:
                logger.info(f"✅ FORWARDING SUCCESS - HTTP {response.status_code}")
                return True
            else:
                logger.error(f"❌ FORWARDING FAILED - HTTP {response.status_code}")
                return False
                
    except Exception as e:
        logger.error(f"❌ FORWARDING EXCEPTION: {str(e)}")
        return False
    finally:
        logger.info(f"=== FORWARDING END ===")

async def safe_emit_to_session(session_id: str, event: str, data: Dict[str, Any]):
    """Safely emit an event to a session, handling cross-instance WebSocket connections"""
    logger.info(f"*** SAFE EMIT START - Session: {session_id}, Event: {event} ***")
    
    # Check if session exists in ElastiCache
    connection_state = await session_manager.get_session_data(session_id, "connection_states")
    if connection_state is None:
        logger.warning(f"❌ Session {session_id} doesn't exist in ElastiCache")
        return False
    
    # First, try to get WebSocket connection from local cache
    target_session = sessions.get(session_id)
    logger.info(f"Local WebSocket found: {target_session is not None}")
    
    if target_session:
        # WebSocket is on this instance - send directly
        logger.info(f"📍 Session {session_id} found locally on {SERVER_ID}")
        
        try:
            target_emitter = SocketIOEmulator(target_session)
            await target_emitter.emit(event, data)
            logger.info(f"✅ LOCAL EMIT SUCCESS for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"❌ LOCAL EMIT FAILED for session {session_id}: {str(e)}")
            await cleanup_session(session_id, target_session)
            return False
    else:
        # WebSocket is not on this instance - check which server has it
        logger.info(f"📍 Session {session_id} not found locally, checking metadata")
        
        connection_metadata = await session_manager.get_connection_metadata(session_id)
        if connection_metadata:
            logger.info(f"🔄 Forwarding to server {connection_metadata['server_id']}")
            result = await forward_to_server_with_websocket(session_id, event, data, connection_metadata)
            logger.info(f"Forwarding result: {'SUCCESS' if result else 'FAILED'}")
            return result
        else:
            logger.warning(f"❌ No connection metadata found for session {session_id}")
            return False

async def handle_register_session(
    socket: SocketIOEmulator, 
    data: Dict[str, Any],
    env: Optional[str] = None,
    token: Optional[str] = None,
    secret: Optional[str] = None,
    uisource: Optional[str] = None
) -> Optional[str]:
    """Handle session registration with efficient batch operations"""
    session_id = data.get("session_id")
    if not session_id:
        logger.warning("Session registration attempted without session_id")
        return None
    
    # Store WebSocket connection in local storage
    sessions[session_id] = socket.websocket
    session_manager.add_websocket_connection(session_id, socket.websocket)
    
    # Prepare all session data for efficient batch operation
    current_time = asyncio.get_event_loop().time()
    session_data = {
        "connection_states": True,
        "last_ping_time": current_time
    }
    
    # Add optional data
    if env:
        session_data["session_environments"] = env
    if token:
        session_data["session_tokens"] = token
    if secret:
        session_data["session_secrets"] = secret
    if uisource:
        session_data["session_uisources"] = uisource
    
    # Batch set all session data efficiently
    await session_manager.set_session_batch(session_id, session_data)
    
    # Set connection metadata separately (different operation)
    await session_manager.set_connection_metadata(session_id, SERVER_IP, SERVER_PORT, SERVER_ID)
    
    # Legacy storage (for backward compatibility during transition)
    connection_states[session_id] = True
    last_ping_time[session_id] = current_time
    if env:
        session_environments[session_id] = env
    if token:
        session_tokens[session_id] = token
    if secret:
        session_secrets[session_id] = secret
    if uisource:
        session_uisources[session_id] = uisource
    
    logger.info(f"Session registered efficiently: {session_id} (env: {env or 'default'}, uisource: {uisource or 'default'})")
    
    # Small delay to ensure connection stability
    await asyncio.sleep(0.1)
    
    # Emit success confirmation
    await socket.emit("session_registered", {
        "session_id": session_id,
        "message": "Session registered successfully",
        "env": env,
        "uisource": uisource
    })
    
    return session_id

async def handle_ping(socket: SocketIOEmulator, data: Dict[str, Any]):
    """Handle keepalive ping with efficient batch update"""
    session_id = data.get("session_id")
    
    if session_id:
        current_time = asyncio.get_event_loop().time()
        
        # Efficient batch update for ping data
        ping_data = {
            "last_ping_time": current_time,
            "connection_states": True
        }
        
        await session_manager.set_session_batch(session_id, ping_data)
        
        # Legacy update (for backward compatibility)
        last_ping_time[session_id] = current_time
        connection_states[session_id] = True
        
        logger.debug(f"Ping processed efficiently: {session_id}")
        
        # Send pong response
        await socket.emit("pong", {
            "session_id": session_id,
            "message": "pong",
            "timestamp": data.get("timestamp"),
            "server_time": current_time
        })
    else:
        logger.warning("Ping received without session_id")

async def make_api_call(payload: Dict[str, Any], session_id: str, token: Optional[str] = None):
    """Fire-and-forget API call to fulfillment service - no response needed"""
    try:
        headers = {"Content-Type": "application/json"}
        
        # Add Authorization header if token is provided
        if token:
            headers["Authorization"] = f"Bearer {token}"
            logger.info(f"Including Authorization header in fulfillment API call for session {session_id}")
        
        # Get fulfillment API URL from environment variable
        fulfillment_url = os.environ.get('FULFILLMENT_API_URL', 'https://ansibleplus.ebiz.verizon.com/ccs/api/fulfillment')
        
        # Fire-and-forget: use a very short timeout and ignore timeout errors
        # We only wait long enough to send the request, not for the response
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=None)) as client:
            # Start the request but don't wait for completion
            try:
                await client.request(
                    method="GET",
                    url=fulfillment_url,
                    json=payload,
                    headers=headers
                )
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout):
                # Ignore timeout errors - request was sent, we don't care about response
                pass
        logger.info(f"API call initiated for session {session_id} (fire-and-forget)")
    except Exception as e:
        # Only log non-timeout errors
        if not isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout)):
            logger.error(f"Fire-and-forget API call failed for session {session_id}: {type(e).__name__} - {str(e)}")

async def handle_chat_request(socket: SocketIOEmulator, data: Dict[str, Any]):
    """Handle chat request with efficient state management"""
    session_id = data.get("session_id")
    
    if not session_id:
        await socket.emit("chat_error", {
            "session_id": session_id,
            "error": "Session ID is required"
        })
        return
    
    # Update session state efficiently
    sessions[session_id] = socket.websocket
    session_manager.add_websocket_connection(session_id, socket.websocket)
    
    current_time = asyncio.get_event_loop().time()
    
    # Batch update session state
    state_data = {
        "connection_states": True,
        "last_ping_time": current_time
    }
    
    await session_manager.set_session_batch(session_id, state_data)
    
    # Legacy update
    connection_states[session_id] = True
    last_ping_time[session_id] = current_time
    
    # Immediately notify client
    success = await safe_emit_to_session(session_id, "chat_started", {
        "session_id": session_id,
        "message": "Processing your request..."
    })
    
    if not success:
        logger.info(f"Session {session_id} disconnected, skipping API call")
        return
    
    # Prepare API payload
    payload = {
        "session_id": session_id,
        "sso_details": data.get("sso_details"),
        "text": data.get("text"),
        "context": data.get("context"),
        "hasAttachments": data.get("hasAttachments", False),
        "agenticai_enabled": data.get("agenticai_enabled", True),
        "is_websocket": True,
        "file": data.get("file", None),
        "content_type": data.get("content_type", None)
    }
    
    # Get session data efficiently with batch operation
    session_data = await session_manager.get_session_batch(session_id, ["session_uisources", "session_tokens", "session_secrets"])
    
    session_uisource = session_data.get("session_uisources")
    if session_uisource and session_uisource.lower() == "slack":
        session_secret = session_data.get("session_secrets")
        payload["secret"] = session_secret
    
    logger.info(f"Making API call for session {session_id}")
    
    # Get token from batch result
    token = session_data.get("session_tokens")
    
    # Fire-and-forget API call
    asyncio.create_task(make_api_call(payload, session_id, token))
    logger.info(f"API call initiated efficiently for session {session_id}")

# Enhanced background task for ElastiCache health and cleanup
async def cleanup_stale_sessions():
    """Enhanced background task with ElastiCache health monitoring"""
    while True:
        try:
            # Perform health check
            health_ok = await session_manager.health_check()
            if not health_ok:
                logger.warning("ElastiCache health check failed, attempting reconnection")
                await session_manager.connect()
            
            # Bulk cleanup stale sessions (every 5 minutes)
            stale_count = await session_manager.bulk_cleanup_stale_sessions(max_age_seconds=7200)
            if stale_count > 0:
                logger.info(f"Cleaned up {stale_count} stale sessions")
            
            # Log cache statistics (every 10 cycles)
            if hasattr(cleanup_stale_sessions, '_cycle_count'):
                cleanup_stale_sessions._cycle_count += 1
            else:
                cleanup_stale_sessions._cycle_count = 1
            
            if cleanup_stale_sessions._cycle_count % 10 == 0:
                cache_info = await session_manager.get_cache_info()
                logger.info(f"Cache health: {cache_info.get('circuit_breaker_state', 'UNKNOWN')}, "
                          f"Local sessions: {cache_info.get('local_cache_entries', 0)}, "
                          f"Connected: {cache_info.get('connected', False)}")
            
        except Exception as e:
            logger.error(f"Error in enhanced cleanup task: {str(e)}")
        
        # Run every 60 seconds
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    """Start background tasks and connect to ElastiCache with enhanced monitoring"""
    logger.info("🚀 Starting WebSocket server with enhanced ElastiCache...")
    
    # Connect to ElastiCache with robust error handling
    connected = await session_manager.connect()
    if connected:
        logger.info("✅ ElastiCache connected with connection pooling and circuit breaker")
        
        # Get initial cache info
        cache_info = await session_manager.get_cache_info()
        logger.info(f"   Redis version: {cache_info.get('redis_version', 'unknown')}")
        logger.info(f"   Connection pool size: {cache_info.get('connection_pool_size', 0)}")
        logger.info(f"   Circuit breaker: {cache_info.get('circuit_breaker_state', 'UNKNOWN')}")
    else:
        logger.warning("⚠️  ElastiCache connection failed - circuit breaker will handle fallback")
    
    # Start enhanced cleanup task with health monitoring
    asyncio.create_task(cleanup_stale_sessions())
    logger.info("✅ Enhanced background task started with health monitoring and bulk cleanup")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    logger.info("Shutting down WebSocket server...")
    await session_manager.disconnect()
    logger.info("ElastiCache connection closed")

@app.get("/ccs/ccs-websocket/health")
async def health_check():
    """Enhanced health check with ElastiCache performance metrics"""
    
    # Get comprehensive cache info
    cache_info = await session_manager.get_cache_info()
    session_stats = await session_manager.get_session_statistics()
    
    active_sessions_count = cache_info.get("application_keys_count", 0) // 7  # Approximate sessions
    local_session_count = len(sessions)
    elasticache_connected = cache_info.get("connected", False)
    
    logger.info(f"Health check - Cache sessions: ~{active_sessions_count}, Local sessions: {local_session_count}, "
               f"Connected: {elasticache_connected}, Circuit breaker: {cache_info.get('circuit_breaker_state', 'UNKNOWN')}")
    
    health_data = {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
        "server_id": SERVER_ID,
        "sessions": {
            "cache_sessions_approx": active_sessions_count,
            "local_sessions": local_session_count
        },
        "elasticache": {
            "connected": elasticache_connected,
            "circuit_breaker_state": cache_info.get("circuit_breaker_state", "UNKNOWN"),
            "circuit_breaker_failures": cache_info.get("circuit_breaker_failures", 0),
            "redis_version": cache_info.get("redis_version", "unknown"),
            "cache_hit_ratio": cache_info.get("cache_hit_ratio", 0),
            "connection_pool_size": cache_info.get("connection_pool_size", 0),
            "local_cache_entries": cache_info.get("local_cache_entries", 0)
        },
        "performance": {
            "total_commands": cache_info.get("total_commands_processed", 0),
            "memory_usage": cache_info.get("used_memory_human", "0B"),
            "connected_clients": cache_info.get("connected_clients", 0)
        }
    }
    
    # Add consistency check if available
    consistency = session_stats.get("consistency_check", {})
    if consistency:
        health_data["consistency"] = {
            "is_consistent": consistency.get("is_consistent", False),
            "cache_only_count": len(consistency.get("cache_only", [])),
            "local_only_count": len(consistency.get("local_only", []))
        }
    
    return health_data

@app.get("/ccs/ccs-websocket/session-data/{session_id}")
async def get_session_data_debug(session_id: str):
    """Get detailed session data for debugging forwarding issues"""
    try:
        # Get all stored data for this session
        session_data = {}
        connection_metadata = None
        local_websocket_info = {}
        
        if session_manager.is_connected():
            # Get all different types of session data
            data_types = [
                "connection_states",
                "last_ping_time", 
                "session_environments",
                "session_tokens",
                "session_secrets", 
                "session_uisources"
            ]
            
            for data_type in data_types:
                session_data[data_type] = await session_manager.get_session_data(session_id, data_type)
            
            # Get connection metadata (which server has the WebSocket)
            connection_metadata = await session_manager.get_connection_metadata(session_id)
        
        # Check local WebSocket connection
        local_websocket = sessions.get(session_id)
        local_websocket_info = {
            "has_local_websocket": local_websocket is not None,
            "websocket_state": local_websocket.client_state.value if local_websocket else None,
            "local_server_id": SERVER_ID,
            "local_server_ip": SERVER_IP,
            "local_server_port": SERVER_PORT
        }
        
        # Check if this session exists in legacy storage too
        legacy_data = {
            "in_sessions_dict": session_id in sessions,
            "in_connection_states": session_id in connection_states,
            "in_legacy_ping_times": session_id in last_ping_time,
            "in_legacy_environments": session_id in session_environments,
            "in_legacy_tokens": session_id in session_tokens,
            "in_legacy_secrets": session_id in session_secrets,
            "in_legacy_uisources": session_id in session_uisources
        }
        
        # Forwarding analysis
        forwarding_analysis = {}
        if connection_metadata:
            is_local = (connection_metadata.get("server_id") == SERVER_ID)
            has_local_websocket = local_websocket is not None
            
            # We should forward if there's no local websocket, regardless of what the metadata says
            should_forward = not has_local_websocket
            
            forwarding_analysis = {
                "should_forward": should_forward,
                "target_server": connection_metadata.get("server_id"),
                "target_ip": connection_metadata.get("server_ip"), 
                "target_port": connection_metadata.get("server_port"),
                "current_server": SERVER_ID,
                "metadata_claims_local": is_local,
                "has_local_websocket": has_local_websocket,
                "forwarding_url": f"https://{connection_metadata.get('server_ip')}:{connection_metadata.get('server_port')}/ccs/ccs-websocket/api/internal/emit"
            }
        
        return {
            "session_id": session_id,
            "timestamp": asyncio.get_event_loop().time(),
            "cache_connected": session_manager.is_connected(),
            "session_data_from_cache": session_data,
            "connection_metadata": connection_metadata,
            "local_websocket_info": local_websocket_info,
            "legacy_storage_data": legacy_data,
            "forwarding_analysis": forwarding_analysis
        }
        
    except Exception as e:
        logger.error(f"Session data debug error for {session_id}: {str(e)}")
        return {
            "error": str(e),
            "session_id": session_id,
            "timestamp": asyncio.get_event_loop().time()
        }

@app.post("/ccs/ccs-websocket/api/notify")
async def notify_session(request: MessageRequest, authorization: Optional[str] = Header(None)):
    """
    Endpoint for external APIs to send messages to WebSocket clients
    Requires JWT authentication via Authorization header
    """
    try:
        # Get session info to determine auth method from ElastiCache
        session_id = request.session_id
        session_uisource = await session_manager.get_session_data(session_id, "session_uisources")
        
        # Authenticate request based on session's uisource
        if session_uisource and session_uisource.lower() == "slack":
            # Validate secret for Slack sessions
            session_secret = await session_manager.get_session_data(session_id, "session_secrets")
            try:
                if not session_secret or not secret_validator.validate_secret(session_secret):
                    error_msg = "Invalid or expired secret for Slack session"
                    logger.info(f"Notify failed for session {session_id}: {error_msg}")
                    raise HTTPException(status_code=401, detail=error_msg)
                logger.info(f"Notify request from Slack session validated: {session_id}")
            except Exception as e:
                error_msg = f"Secret validation error: {str(e)}"
                logger.info(f"Notify failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        else:
            # JWT-based authentication (existing logic)
            if not authorization:
                error_msg = "Authorization header required"
                logger.info(f"Notify failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            token = authenticator.extract_token_from_header(authorization)
            if not token:
                error_msg = "Invalid authorization header format"
                logger.info(f"Notify failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            # Verify token (use session's env if available, otherwise default)
            env = await session_manager.get_session_data(session_id, "session_environments") or "DEV"
            decoded = authenticator.verify_jwt_token(token, env)
            
            if not decoded:
                error_msg = "Invalid or expired JWT token"
                logger.info(f"Notify failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        
        message = request.message
        
        logger.info(f"Received notification for session {session_id}: {message}")
        
        # Check if session exists in ElastiCache
        connection_state = await session_manager.get_session_data(session_id, "connection_states")
        if connection_state is None:
            error_msg = f"Session {session_id} not found in ElastiCache"
            logger.info(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        
        # Check if session is still connected
        if not connection_state:
            error_msg = f"Session {session_id} is not connected"
            logger.info(error_msg)
            # Emit error to session
            await safe_emit_to_session(session_id, "chat_error", {
                "session_id": session_id,
                "error": "Session disconnected",
                "message": error_msg
            })
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Send notification to the WebSocket client
        success = await safe_emit_to_session(session_id, "notification", {
            "session_id": session_id,
            "message": message
        })
        
        if success:
            logger.info(f"Notification sent to session {session_id}")
            return {"status": "success", "message": "Notification sent successfully"}
        else:
            error_msg = f"Failed to send notification to session {session_id}"
            logger.info(error_msg)
            # Try to emit error to session
            await safe_emit_to_session(session_id, "chat_error", {
                "session_id": session_id,
                "error": "Send failed",
                "message": error_msg
            })
            raise HTTPException(status_code=400, detail=error_msg)
        
    except HTTPException:
        # Re-raise HTTPException so FastAPI handles it properly
        raise
    except Exception as e:
        error_msg = f"Internal server error: {str(e)}"
        logger.info(f"Error sending notification: {str(e)}")
        # Try to emit error to session if we have session_id
        try:
            if request.session_id in sessions:
                await safe_emit_to_session(request.session_id, "chat_error", {
                    "session_id": request.session_id,
                    "error": "Server error",
                    "message": error_msg
                })
        except:
            pass
        raise HTTPException(status_code=500, detail=error_msg)
    
@app.post("/ccs/ccs-websocket/api/finalnotify")
async def final_notify_session(request: FinalMessageRequest, authorization: Optional[str] = Header(None)):
    """
    Endpoint for external APIs to send messages to WebSocket clients
    Requires JWT authentication via Authorization header
    """
    try:
        # Get session info to determine auth method from ElastiCache
        session_id = request.session_id
        session_uisource = await session_manager.get_session_data(session_id, "session_uisources")
        
        # Authenticate request based on session's uisource
        if session_uisource and session_uisource.lower() == "slack":
            # Validate secret for Slack sessions
            session_secret = await session_manager.get_session_data(session_id, "session_secrets")
            try:
                if not session_secret or not secret_validator.validate_secret(session_secret):
                    error_msg = "Invalid or expired secret for Slack session"
                    logger.info(f"Final notify failed for session {session_id}: {error_msg}")
                    raise HTTPException(status_code=401, detail=error_msg)
                logger.info(f"Final notify request from Slack session validated: {session_id}")
            except Exception as e:
                error_msg = f"Secret validation error: {str(e)}"
                logger.info(f"Final notify failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        else:
            # JWT-based authentication (existing logic)
            if not authorization:
                error_msg = "Authorization header required"
                logger.info(f"Final notify failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            token = authenticator.extract_token_from_header(authorization)
            if not token:
                error_msg = "Invalid authorization header format"
                logger.info(f"Final notify failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            # Verify token (use session's env if available, otherwise default)
            env = await session_manager.get_session_data(session_id, "session_environments") or "DEV"
            decoded = authenticator.verify_jwt_token(token, env)
            
            if not decoded:
                error_msg = "Invalid or expired JWT token"
                logger.info(f"Final notify failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        
        message = request.message
        
        query_id = request.query_id

        logger.info(f"Received final notification for session {session_id}: {message} with query_id: {query_id}")
        
        logger.info(f"🔍 PRODUCTION DEBUG - Session lookup for {session_id}")
        
        # Get session data from ElastiCache
        connection_state = await session_manager.get_session_data(session_id, "connection_states")
        all_connection_states = await session_manager.get_all_sessions("connection_states")
        local_sessions = session_manager.get_all_websocket_sessions()
        
        logger.info(f"📊 Total ElastiCache sessions: {len(all_connection_states)}")
        logger.info(f"🔑 ElastiCache session IDs: {list(all_connection_states.keys())}")
        logger.info(f"📊 Total local WebSocket sessions: {len(local_sessions)}")
        logger.info(f"🔑 Local WebSocket session IDs: {list(local_sessions.keys())}")
        logger.info(f"✅ Session exists in ElastiCache: {connection_state is not None}")
        logger.info(f"🔗 Connection state: {connection_state if connection_state is not None else 'NOT_FOUND'}")
        
        # Check if session exists in ElastiCache
        if connection_state is None:
            error_msg = f"Session {session_id} not found in ElastiCache - Available sessions: {list(all_connection_states.keys())}"
            logger.error(f"❌ {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)

        
        # Check if session is still connected
        if not connection_state:
            error_msg = f"Session {session_id} is not connected"
            logger.info(error_msg)
            # Emit error to session
            await safe_emit_to_session(session_id, "chat_error", {
                "session_id": session_id,
                "error": "Session disconnected",
                "message": error_msg
            })
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Prepare notification payload with query_id if available
        notification_payload = {
            "session_id": session_id,
            "message": message,
            "query_id": query_id
        }

        if request.references:
            notification_payload["references"] = request.references
        
        # Send notification to the WebSocket client
        success = await safe_emit_to_session(session_id, "final_notification", notification_payload)
        
        if success:
            logger.info(f"final notification sent to session {session_id}")
            return {"status": "success", "message": "Final Notification sent successfully"}
        else:
            error_msg = f"Failed to send final notification to session {session_id}"
            logger.info(error_msg)
            # Try to emit error to session
            await safe_emit_to_session(session_id, "chat_error", {
                "session_id": session_id,
                "error": "Send failed",
                "message": error_msg
            })
            raise HTTPException(status_code=400, detail=error_msg)
        
    except HTTPException:
        # Re-raise HTTPException so FastAPI handles it properly
        raise
    except Exception as e:
        error_msg = f"Internal server error: {str(e)}"
        logger.info(f"Error sending final notification: {str(e)}")
        # Try to emit error to session if we have session_id
        try:
            if request.session_id in sessions:
                await safe_emit_to_session(request.session_id, "chat_error", {
                    "session_id": request.session_id,
                    "error": "Server error",
                    "message": error_msg
                })
        except:
            pass
        raise HTTPException(status_code=500, detail=error_msg)
    
@app.post("/ccs/ccs-websocket/api/livestatus")
async def livestatus_notify(request: MessageRequest, authorization: Optional[str] = Header(None)):
    """
    Endpoint for external APIs to send live status messages to WebSocket clients
    Requires JWT authentication via Authorization header
    """
    try:
        # Get session info to determine auth method from ElastiCache
        session_id = request.session_id
        session_uisource = await session_manager.get_session_data(session_id, "session_uisources")
        
        # Authenticate request based on session's uisource
        if session_uisource and session_uisource.lower() == "slack":
            # Validate secret for Slack sessions
            session_secret = await session_manager.get_session_data(session_id, "session_secrets")
            try:
                if not session_secret or not secret_validator.validate_secret(session_secret):
                    error_msg = "Invalid or expired secret for Slack session"
                    logger.info(f"Live status failed for session {session_id}: {error_msg}")
                    raise HTTPException(status_code=401, detail=error_msg)
                logger.info(f"Live status request from Slack session validated: {session_id}")
            except Exception as e:
                error_msg = f"Secret validation error: {str(e)}"
                logger.info(f"Live status failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        else:
            # JWT-based authentication (existing logic)
            if not authorization:
                error_msg = "Authorization header required"
                logger.info(f"Live status failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            token = authenticator.extract_token_from_header(authorization)
            if not token:
                error_msg = "Invalid authorization header format"
                logger.info(f"Live status failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            # Verify token (use session's env if available, otherwise default)
            env = await session_manager.get_session_data(session_id, "session_environments") or "DEV"
            decoded = authenticator.verify_jwt_token(token, env)
            
            if not decoded:
                error_msg = "Invalid or expired JWT token"
                logger.info(f"Live status failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        
        message = request.message

        logger.info(f"Received live status update for session {session_id}: {message}")

        # Check if session exists in ElastiCache
        connection_state = await session_manager.get_session_data(session_id, "connection_states")
        if connection_state is None:
            error_msg = f"Session {session_id} not found in ElastiCache"
            logger.info(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        
        # Check if session is still connected
        if not connection_state:
            error_msg = f"Session {session_id} is not connected"
            logger.info(error_msg)
            # Emit error to session
            await safe_emit_to_session(session_id, "chat_error", {
                "session_id": session_id,
                "error": "Session disconnected",
                "message": error_msg
            })
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Send notification to the WebSocket client
        success = await safe_emit_to_session(session_id, "livestatus", {
            "session_id": session_id,
            "message": message
        })
        
        if success:
            logger.info(f"Live status sent to session {session_id}")
            return {"status": "success", "message": "Live status sent successfully"}
        else:
            error_msg = f"Failed to send live status to session {session_id}"
            logger.info(error_msg)
            # Try to emit error to session
            await safe_emit_to_session(session_id, "chat_error", {
                "session_id": session_id,
                "error": "Send failed",
                "message": error_msg
            })
            raise HTTPException(status_code=400, detail=error_msg)
        
    except HTTPException:
        # Re-raise HTTPException so FastAPI handles it properly
        raise
    except Exception as e:
        error_msg = f"Internal server error: {str(e)}"
        logger.info(f"Error sending live status: {str(e)}")
        # Try to emit error to session if we have session_id
        try:
            if request.session_id in sessions:
                await safe_emit_to_session(request.session_id, "chat_error", {
                    "session_id": request.session_id,
                    "error": "Server error",
                    "message": error_msg
                })
        except:
            pass
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/ccs/ccs-websocket/api/feedback")
async def feedback_session(request: FeedbackRequest, authorization: Optional[str] = Header(None)):
    """
    Endpoint to submit feedback
    Requires JWT authentication via Authorization header
    """
    try:
        session_id = request.session_id
        session_uisource = await session_manager.get_session_data(session_id, "session_uisources")
        
        # Authenticate request based on session's uisource
        if session_uisource and session_uisource.lower() == "slack":
            # Validate secret for Slack sessions
            session_secret = await session_manager.get_session_data(session_id, "session_secrets")
            try:
                if not session_secret or not secret_validator.validate_secret(session_secret):
                    error_msg = "Invalid or expired secret for Slack session"
                    logger.info(f"Feedback failed for session {session_id}: {error_msg}")
                    raise HTTPException(status_code=401, detail=error_msg)
                logger.info(f"Feedback request from Slack session validated: {session_id}")
            except Exception as e:
                error_msg = f"Secret validation error: {str(e)}"
                logger.info(f"Feedback failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        else:
            # Authenticate request
            if not authorization:
                error_msg = "Authorization header required"
                logger.info(f"Feedback failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
            
            token = authenticator.extract_token_from_header(authorization)
            if not token:
                error_msg = "Invalid authorization header format"
                logger.info(f"Feedback failed: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        
            # Verify token (use session's env if available, otherwise default)
            env = await session_manager.get_session_data(session_id, "session_environments") or "DEV"
            decoded = authenticator.verify_jwt_token(token, env)
            
            if not decoded:
                error_msg = "Invalid or expired JWT token"
                logger.info(f"Feedback failed for session {session_id}: {error_msg}")
                raise HTTPException(status_code=401, detail=error_msg)
        
        # Extract feedback data from request
        vzid = request.vzid
        query_id = request.query_id
        feedback = request.feedback
        
        # Log the feedback data
        logger.info(f"Received feedback - session_id: {session_id}, vzid: {vzid}, query_id: {query_id}, feedback: {feedback}")
        
        # Call the log fulfillment API
        try:
            payload = {
                "operation": "log",
                "log_type": "agentic",
                "is_agentic": "true",
                "table_name": "agent_feedback",
                "data": {
                    "ui_queries_id": query_id,
                    "feedback": feedback,
                }
            }
            
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            
            log_fulfillment_url = os.environ.get('LOG_FULFILLMENT_API_URL', 'https://ansibleplus.ebiz.verizon.com/ccs/api/logfulfillment')
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.post(
                    url=log_fulfillment_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"Feedback successfully logged to fulfillment API for session {session_id}")
                else:
                    logger.warning(f"Log fulfillment API returned status {response.status_code} for session {session_id}")
                    
        except Exception as api_error:
            logger.error(f"Failed to call log fulfillment API for session {session_id}: {str(api_error)}")
            # Continue processing - don't fail the feedback submission if logging fails
        
        return {
            "status": "success",
            "message": "Feedback submitted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Internal server error: {str(e)}"
        logger.info(f"Error processing feedback: {str(e)}")
        
        try:
            if request.session_id in sessions:
                await safe_emit_to_session(request.session_id, "chat_error", {
                    "session_id": request.session_id,
                    "error": "Server error",
                    "message": error_msg
                })
        except:
            pass
        
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/ccs/ccs-websocket/api/internal/emit")
async def internal_emit(request: InternalEmitRequest):
    """
    Internal endpoint for server-to-server WebSocket message forwarding
    This endpoint is called by other instances when they need to send a message
    to a WebSocket connection that lives on this instance
    """
    try:
        session_id = request.session_id
        event = request.event
        data = request.data
        
        logger.info(f"🔄 Internal emit request received for session {session_id}, event: {event}")
        
        # Get WebSocket connection from LOCAL cache only (this is the target server)
        target_session = sessions.get(session_id)
        if target_session:
            try:
                # Send directly to the WebSocket
                target_emitter = SocketIOEmulator(target_session)
                await target_emitter.emit(event, data)
                logger.info(f"✅ Internal emit successful for session {session_id}")
                return {"status": "success", "message": "Message sent to WebSocket"}
            except Exception as e:
                logger.error(f"❌ Internal emit failed for session {session_id}: {str(e)}")
                # Clean up the failed session
                await cleanup_session(session_id, target_session)
                return {"status": "error", "message": f"Failed to send message: {str(e)}"}
        else:
            error_msg = f"WebSocket connection for session {session_id} not found on this server"
            logger.warning(f"⚠️  {error_msg}")
            return {"status": "error", "message": error_msg}
            
    except Exception as e:
        error_msg = f"Internal emit error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"status": "error", "message": error_msg}

if __name__ == "__main__":
    import socket
    
    # No command-line arguments needed!
    # - Region is AUTO-DETECTED from EC2 instance metadata
    # - JWT authentication uses 'env' query parameter in WebSocket URL
    # 
    # Usage: python ccs_onecloud_websocket.py
    
    detected_region = cw_logger.region  # Get the auto-detected region
    
    logger.info(f"✅ CloudWatch Region (auto-detected): {detected_region}")
    
    # Get the local IP address
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "localhost"
    
    logger.info("=" * 60)
    logger.info("🚀 WebSocket Server Starting...")
    logger.info("=" * 60)
    logger.info(f"📡 Server Host: 0.0.0.0")
    logger.info(f"📡 Server Port: {server_port}")
    logger.info(f"🌐 Machine IP: {local_ip}")
    logger.info(f"📍 CloudWatch Region: {detected_region} (auto-detected)")
    logger.info(f"☁️  CloudWatch Log Group: /aws/ec2/ccs-websocket")
    logger.info(f"📁 Log File: {log_filepath}")
    logger.info("")
    logger.info("🔗 Access URLs:")
    
    # Get SSL certificate paths from environment variables
    pemFilePath = os.environ.get('pemFilePath')
    keyFilePath = os.environ.get('keyFilePath')
    
    # Determine protocol based on SSL configuration
    ws_protocol = "wss" if pemFilePath and keyFilePath else "ws"
    http_protocol = "https" if pemFilePath and keyFilePath else "http"
    
    logger.info(f"   WebSocket (JWT): {ws_protocol}://{local_ip}:{server_port}/ccs/ccs-websocket/ws?Authorization=Bearer%20<token>&env=PROD")
    logger.info(f"   WebSocket (Slack): {ws_protocol}://{local_ip}:{server_port}/ccs/ccs-websocket/ws?secret=<secret>&uisource=slack")
    logger.info(f"   Health Check:  {http_protocol}://{local_ip}:{server_port}/ccs/ccs-websocket/health")
    logger.info(f"   Sessions:      {http_protocol}://{local_ip}:{server_port}/ccs/ccs-websocket/sessions")
    logger.info(f"   Notify API:    {http_protocol}://{local_ip}:{server_port}/ccs/ccs-websocket/api/notify")
    logger.info("")
    logger.info("📝 JWT Auth: Use 'Authorization=Bearer <token>&env=(PROD/NONPROD/DEV)' in WebSocket URL")
    logger.info("📝 Secret Auth: Use 'secret=<secret>&uisource=slack' in WebSocket URL for Slack integration")
    logger.info("📝 CloudWatch: Region auto-detected from EC2, Log group is unique")
    logger.info("💡 Usage: python ccs_onecloud_websocket.py")
    logger.info("=" * 60)
    
    # Log final startup message
    logger.info(f"WebSocket server starting on port {server_port}")
    logger.info(f"CloudWatch logging: Region={detected_region} (auto-detected)")
    logger.info("JWT authentication: Use 'Authorization' + 'env' query parameters")
    logger.info("Secret authentication: Use 'secret' + 'uisource' query parameters")
    logger.info("Active sessions will be tracked by session_id")
    logger.info("Auto-disconnect disabled - sessions remain active until client disconnects")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=server_port,
        ssl_certfile=pemFilePath,
        ssl_keyfile=keyFilePath,
        log_level="info",
        timeout_keep_alive=900,  # Keep connections alive for 15 minutes (longer than 300s processing)
        ws_ping_interval=20,     # Send ping every 20 seconds to keep connection alive
        ws_ping_timeout=10       # Wait 10 seconds for pong response
    )