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

# Create separate logger for message forwarding and emission operations
forwarding_log_filepath = os.path.join(log_dir, f"forwarding_logs_{ip_addr_log}_{logfile_timestamp}.log")
forwarding_logger = logging.getLogger(f'message_forwarding_{ip_addr_log}')
forwarding_logger.setLevel(logging.INFO)

# Create file handler for forwarding logger
forwarding_file_handler = logging.FileHandler(forwarding_log_filepath, encoding='utf-8')
forwarding_file_handler.setLevel(logging.INFO)
forwarding_formatter = logging.Formatter(
    '%(asctime)s - [FORWARDING] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
forwarding_file_handler.setFormatter(forwarding_formatter)
forwarding_logger.addHandler(forwarding_file_handler)
forwarding_logger.propagate = False  # Prevent duplicate logs in main logger

logger.info(f"Message forwarding logging initialized: {forwarding_log_filepath}")

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
forwarding_logger.info(f"Message forwarding logger started for server {SERVER_ID}")

# Test the forwarding logger to ensure it's working
forwarding_logger.info(f"🔧 Forwarding logger test - Server ID: {SERVER_ID}")
forwarding_logger.info(f"🔧 Forwarding logger test - Log file: {forwarding_log_filepath}")
forwarding_logger.info(f"🔧 Forwarding logger test - Logger level: {forwarding_logger.level}")
forwarding_logger.info(f"🔧 Forwarding logger test - Handlers count: {len(forwarding_logger.handlers)}")

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
        local_sessions = session_manager.get_all_websocket_sessions()
        for sid, session_socket in local_sessions.items():
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
    forwarding_start_time = asyncio.get_event_loop().time()
    forwarding_logger.info(f"=== FORWARDING START ===")
    forwarding_logger.info(f"Session ID: {session_id}")
    forwarding_logger.info(f"Event: {event}")
    forwarding_logger.info(f"Source server: {SERVER_ID} ({SERVER_IP}:{SERVER_PORT})")
    forwarding_logger.info(f"Target server: {server_info.get('server_id', 'UNKNOWN')}")
    forwarding_logger.info(f"Target IP: {server_info.get('server_ip', 'UNKNOWN')}")
    forwarding_logger.info(f"Target port: {server_info.get('server_port', 'UNKNOWN')}")
    forwarding_logger.info(f"Data payload: {json.dumps(data, indent=2) if data else 'None'}")
    
    try:
        # Make HTTP call to the server that has the WebSocket
        target_url = f"https://{server_info['server_ip']}:{server_info['server_port']}/ccs/ccs-websocket/api/internal/emit"
        
        payload = {
            "session_id": session_id,
            "event": event,
            "data": data
        }
        
        payload_size = len(json.dumps(payload))
        forwarding_logger.info(f"Target URL: {target_url}")
        forwarding_logger.info(f"Payload size: {payload_size} characters")
        forwarding_logger.info(f"Full payload: {json.dumps(payload, indent=2)}")
        
        logger.info(f"🔄 Attempting to forward {event} for session {session_id}")
        logger.info(f"   Target URL: {target_url}")
        logger.info(f"   Target server: {server_info['server_id']}")
        logger.info(f"   Payload size: {len(str(payload))} chars")
        
        http_start_time = asyncio.get_event_loop().time()
        forwarding_logger.info(f"Starting HTTP request at: {http_start_time}")
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(target_url, json=payload)
            
            http_end_time = asyncio.get_event_loop().time()
            http_duration = http_end_time - http_start_time
            forwarding_logger.info(f"HTTP request completed in: {http_duration:.3f} seconds")
            forwarding_logger.info(f"HTTP Response status: {response.status_code}")
            forwarding_logger.info(f"HTTP Response headers: {dict(response.headers)}")
            
            logger.info(f"   HTTP Response: {response.status_code}")
            if hasattr(response, 'text'):
                response_text = await response.aread()
                response_body = response_text.decode()
                forwarding_logger.info(f"HTTP Response body: {response_body}")
                logger.info(f"   Response body: {response_body[:200]}...")
            
            if response.status_code == 200:
                forwarding_total_time = asyncio.get_event_loop().time() - forwarding_start_time
                forwarding_logger.info(f"✅ FORWARDING SUCCESS - Total time: {forwarding_total_time:.3f} seconds")
                forwarding_logger.info(f"Message successfully forwarded to {server_info['server_id']} for session {session_id}")
                logger.info(f"✅ Message forwarded to {server_info['server_id']} for session {session_id}")
                return True
            else:
                forwarding_total_time = asyncio.get_event_loop().time() - forwarding_start_time
                forwarding_logger.error(f"❌ FORWARDING FAILED - HTTP {response.status_code} - Total time: {forwarding_total_time:.3f} seconds")
                forwarding_logger.error(f"Failed to forward to {server_info['server_id']}: HTTP {response.status_code}")
                logger.error(f"❌ Forwarding failed to {server_info['server_id']}: HTTP {response.status_code}")
                return False
                
    except Exception as e:
        forwarding_total_time = asyncio.get_event_loop().time() - forwarding_start_time
        forwarding_logger.error(f"❌ FORWARDING EXCEPTION - Total time: {forwarding_total_time:.3f} seconds")
        forwarding_logger.error(f"Exception type: {type(e).__name__}")
        forwarding_logger.error(f"Exception message: {str(e)}")
        forwarding_logger.error(f"Server info: {json.dumps(server_info, indent=2)}")
        forwarding_logger.error(f"Session ID: {session_id}")
        forwarding_logger.error(f"Event: {event}")
        
        logger.error(f"❌ Forwarding error to {server_info['server_id']}: {e}")
        logger.error(f"   Exception type: {type(e).__name__}")
        logger.error(f"   Server info: {server_info}")
        return False
    finally:
        forwarding_logger.info(f"=== FORWARDING END ===")

async def safe_emit_to_session(session_id: str, event: str, data: Dict[str, Any]):
    """Safely emit an event to a session, handling cross-instance WebSocket connections"""
    emit_start_time = asyncio.get_event_loop().time()
    forwarding_logger.info(f"*** SAFE EMIT START ***")
    forwarding_logger.info(f"Session ID: {session_id}")
    forwarding_logger.info(f"Event: {event}")
    forwarding_logger.info(f"Current server: {SERVER_ID} ({SERVER_IP}:{SERVER_PORT})")
    forwarding_logger.info(f"Data payload: {json.dumps(data, indent=2) if data else 'None'}")
    
    # Check if session exists in ElastiCache
    cache_check_start = asyncio.get_event_loop().time()
    connection_state = await session_manager.get_session_data(session_id, "connection_states")
    cache_check_duration = asyncio.get_event_loop().time() - cache_check_start
    forwarding_logger.info(f"Cache check completed in: {cache_check_duration:.3f} seconds")
    forwarding_logger.info(f"Connection state from cache: {connection_state}")
    
    if connection_state is None:
        forwarding_logger.warning(f"❌ Session {session_id} doesn't exist in ElastiCache")
        logger.warning(f"Session {session_id} doesn't exist in ElastiCache")
        return False
    
    logger.info(f"🔍 Emitting {event} to session {session_id}")
    
    # First, try to get WebSocket connection from local cache
    local_lookup_start = asyncio.get_event_loop().time()
    target_session = session_manager.get_websocket_connection(session_id)
    local_lookup_duration = asyncio.get_event_loop().time() - local_lookup_start
    forwarding_logger.info(f"Local WebSocket lookup completed in: {local_lookup_duration:.3f} seconds")
    forwarding_logger.info(f"Local WebSocket found: {target_session is not None}")
    
    if target_session:
        # WebSocket is on this instance - send directly
        forwarding_logger.info(f"📍 Session {session_id} found locally on {SERVER_ID}")
        forwarding_logger.info(f"WebSocket state: {target_session.client_state.value if hasattr(target_session, 'client_state') else 'UNKNOWN'}")
        logger.info(f"   📍 Session {session_id} found locally on {SERVER_ID}")
        
        try:
            emit_local_start = asyncio.get_event_loop().time()
            target_emitter = SocketIOEmulator(target_session)
            await target_emitter.emit(event, data)
            emit_local_duration = asyncio.get_event_loop().time() - emit_local_start
            
            total_emit_time = asyncio.get_event_loop().time() - emit_start_time
            forwarding_logger.info(f"✅ LOCAL EMIT SUCCESS - Emit time: {emit_local_duration:.3f}s, Total time: {total_emit_time:.3f}s")
            forwarding_logger.info(f"Message sent locally to session {session_id} with event {event}")
            logger.debug(f"✅ Message sent locally to session {session_id}")
            return True
        except Exception as e:
            total_emit_time = asyncio.get_event_loop().time() - emit_start_time
            forwarding_logger.error(f"❌ LOCAL EMIT FAILED - Total time: {total_emit_time:.3f}s")
            forwarding_logger.error(f"Exception type: {type(e).__name__}")
            forwarding_logger.error(f"Exception message: {str(e)}")
            forwarding_logger.error(f"Session ID: {session_id}")
            forwarding_logger.error(f"Event: {event}")
            forwarding_logger.error(f"WebSocket state before failure: {target_session.client_state.value if hasattr(target_session, 'client_state') else 'UNKNOWN'}")
            
            logger.error(f"Failed to send {event} to local session {session_id}: {str(e)}")
            # Only remove the session on actual send failure
            forwarding_logger.info(f"Initiating session cleanup for {session_id}")
            await cleanup_session(session_id, target_session)
            forwarding_logger.info(f"Session cleanup completed for {session_id}")
            return False
    else:
        # WebSocket is not on this instance - check which server has it
        forwarding_logger.info(f"📍 Session {session_id} not found locally on {SERVER_ID}")
        logger.info(f"   📍 Session {session_id} not found locally on {SERVER_ID}")
        
        metadata_lookup_start = asyncio.get_event_loop().time()
        connection_metadata = await session_manager.get_connection_metadata(session_id)
        metadata_lookup_duration = asyncio.get_event_loop().time() - metadata_lookup_start
        forwarding_logger.info(f"Connection metadata lookup completed in: {metadata_lookup_duration:.3f} seconds")
        forwarding_logger.info(f"Connection metadata: {json.dumps(connection_metadata, indent=2) if connection_metadata else 'None'}")
        
        if connection_metadata:
            # Forward to whatever server is listed in metadata
            forwarding_logger.info(f"🔄 Session {session_id} is on server {connection_metadata['server_id']}, forwarding message")
            forwarding_logger.info(f"Current server: {SERVER_ID}")
            forwarding_logger.info(f"Target server: {connection_metadata['server_id']}")
            forwarding_logger.info(f"Target IP: {connection_metadata['server_ip']}")
            forwarding_logger.info(f"Target Port: {connection_metadata['server_port']}")
            
            logger.info(f"🔄 Session {session_id} is on server {connection_metadata['server_id']}, forwarding message")
            logger.info(f"   Current server: {SERVER_ID}")
            logger.info(f"   Target server: {connection_metadata['server_id']}")
            logger.info(f"   Target IP: {connection_metadata['server_ip']}")
            logger.info(f"   Target Port: {connection_metadata['server_port']}")
            
            forward_start_time = asyncio.get_event_loop().time()
            result = await forward_to_server_with_websocket(session_id, event, data, connection_metadata)
            forward_duration = asyncio.get_event_loop().time() - forward_start_time
            total_emit_time = asyncio.get_event_loop().time() - emit_start_time
            
            forwarding_logger.info(f"Forwarding completed in: {forward_duration:.3f}s, Total emit time: {total_emit_time:.3f}s")
            forwarding_logger.info(f"Forwarding result: {'SUCCESS' if result else 'FAILED'}")
            
            return result
        else:
            total_emit_time = asyncio.get_event_loop().time() - emit_start_time
            forwarding_logger.warning(f"❌ Session {session_id} connection metadata not found - Total time: {total_emit_time:.3f}s")
            forwarding_logger.warning(f"Session may have been cleaned up or never properly registered")
            logger.warning(f"❌ Session {session_id} connection metadata not found - session may have been cleaned up")
            return False

async def handle_register_session(
    socket: SocketIOEmulator, 
    data: Dict[str, Any],
    env: Optional[str] = None,
    token: Optional[str] = None,
    secret: Optional[str] = None,
    uisource: Optional[str] = None
) -> Optional[str]:
    """Handle session registration - only called after successful authentication"""
    session_id = data.get("session_id")
    if not session_id:
        logger.warning("Session registration attempted without session_id")
        return None
    
    # Register the session in ElastiCache
    session_manager.add_websocket_connection(session_id, socket.websocket)
    await session_manager.set_session_data(session_id, "connection_states", True)
    await session_manager.set_session_data(session_id, "last_ping_time", asyncio.get_event_loop().time())
    
    # Store connection metadata - which server has the WebSocket
    await session_manager.set_connection_metadata(session_id, SERVER_IP, SERVER_PORT, SERVER_ID)
    
    # Store environment, token, secret, and uisource for future validation in ElastiCache
    if env:
        await session_manager.set_session_data(session_id, "session_environments", env)
    if token:
        await session_manager.set_session_data(session_id, "session_tokens", token)
    if secret:
        await session_manager.set_session_data(session_id, "session_secrets", secret)
    if uisource:
        await session_manager.set_session_data(session_id, "session_uisources", uisource)
    
    # Legacy storage (for backward compatibility during transition)
    sessions[session_id] = socket.websocket
    connection_states[session_id] = True
    last_ping_time[session_id] = asyncio.get_event_loop().time()
    if env:
        session_environments[session_id] = env
    if token:
        session_tokens[session_id] = token
    if secret:
        session_secrets[session_id] = secret
    if uisource:
        session_uisources[session_id] = uisource
    
    logger.info(f"Session registered in ElastiCache: {session_id} (env: {env or 'default'}, uisource: {uisource or 'default'})")
    
    # Small delay to ensure connection is stable
    await asyncio.sleep(0.1)
    
    # Emit success confirmation to client
    await socket.emit("session_registered", {
        "session_id": session_id,
        "message": "Session registered successfully",
        "env": env,
        "uisource": uisource
    })
    
    return session_id

async def handle_ping(socket: SocketIOEmulator, data: Dict[str, Any]):
    """Handle keepalive ping from client"""
    session_id = data.get("session_id")
    
    if session_id:
        # Update last ping time in ElastiCache
        current_time = asyncio.get_event_loop().time()
        await session_manager.set_session_data(session_id, "last_ping_time", current_time)
        await session_manager.set_session_data(session_id, "connection_states", True)
        
        # Legacy update (for backward compatibility during transition)
        last_ping_time[session_id] = current_time
        connection_states[session_id] = True
        
        logger.debug(f"Keepalive ping received from session: {session_id}")
        
        # Send pong response back to client
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
    """Handle chat request"""
    session_id = data.get("session_id")
    
    if not session_id:
        await socket.emit("chat_error", {
            "session_id": session_id,
            "error": "Session ID is required"
        })
        return
    
    # Store/update session connection in ElastiCache and local cache
    session_manager.add_websocket_connection(session_id, socket.websocket)
    current_time = asyncio.get_event_loop().time()
    await session_manager.set_session_data(session_id, "connection_states", True)
    await session_manager.set_session_data(session_id, "last_ping_time", current_time)
    
    # Legacy storage (for backward compatibility during transition)
    sessions[session_id] = socket.websocket
    connection_states[session_id] = True
    last_ping_time[session_id] = current_time
    
    # 1. Immediately notify client that request started
    success = await safe_emit_to_session(session_id, "chat_started", {
        "session_id": session_id,
        "message": "Processing your request..."
    })
    
    if not success:
        logger.info(f"Session {session_id} disconnected, skipping API call")
        return

    
    # 2. Call the AgenticAI API (fire-and-forget)
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
    
    # Get UI source from ElastiCache
    session_uisource = await session_manager.get_session_data(session_id, "session_uisources")
    if session_uisource and session_uisource.lower() == "slack":
        # Get the stored secret for this session from ElastiCache
        session_secret = await session_manager.get_session_data(session_id, "session_secrets")
        payload["secret"] = session_secret
        
    
    logger.info(f"Making API call for session {session_id}")
    
    # Get the stored JWT token for this session from ElastiCache
    token = await session_manager.get_session_data(session_id, "session_tokens")
    
    # Fire-and-forget API call - don't wait for response
    asyncio.create_task(make_api_call(payload, session_id, token))
    
    logger.info(f"API call initiated for session {session_id} (fire-and-forget)")

# Background task to clean up stale sessions
async def cleanup_stale_sessions():
    """Background task kept running but auto-disconnect disabled"""
    while True:
        try:
            # Auto-disconnect disabled - sessions remain active indefinitely
            # Sessions are only cleaned up when client explicitly disconnects or on send failure
            pass
            
        except Exception as e:
            logger.error(f"Error in cleanup task: {str(e)}")
        
        # Run cleanup every 60 seconds
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    """Start background tasks and connect to ElastiCache"""
    # Test forwarding logger on startup
    forwarding_logger.info(f"🚀 STARTUP EVENT - Testing forwarding logger")
    forwarding_logger.info(f"🚀 STARTUP EVENT - Current server: {SERVER_ID}")
    forwarding_logger.info(f"🚀 STARTUP EVENT - Forwarding log file: {forwarding_log_filepath}")
    
    # Connect to ElastiCache
    connected = await session_manager.connect()
    if connected:
        logger.info("✅ ElastiCache connection established successfully")
        forwarding_logger.info("✅ ElastiCache connection established for forwarding operations")
    else:
        logger.warning("⚠️  ElastiCache connection failed - using local fallback storage")
        forwarding_logger.warning("⚠️  ElastiCache connection failed - forwarding may be impacted")
    
    # Start cleanup task
    asyncio.create_task(cleanup_stale_sessions())
    logger.info("Background task started (auto-disconnect disabled)")
    forwarding_logger.info("🔄 Background cleanup task started")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    logger.info("Shutting down WebSocket server...")
    await session_manager.disconnect()
    logger.info("ElastiCache connection closed")

@app.get("/ccs/ccs-websocket/test/forwarding-logger")
async def test_forwarding_logger():
    """Test endpoint to verify forwarding logger is working"""
    test_timestamp = asyncio.get_event_loop().time()
    
    # Test all log levels
    forwarding_logger.info(f"🧪 FORWARDING LOGGER TEST - INFO level - Timestamp: {test_timestamp}")
    forwarding_logger.warning(f"🧪 FORWARDING LOGGER TEST - WARNING level - Timestamp: {test_timestamp}")
    forwarding_logger.error(f"🧪 FORWARDING LOGGER TEST - ERROR level - Timestamp: {test_timestamp}")
    
    # Test detailed logging similar to what's used in the methods
    forwarding_logger.info(f"=== TEST FORWARDING START ===")
    forwarding_logger.info(f"Session ID: test_session_{test_timestamp}")
    forwarding_logger.info(f"Event: test_event")
    forwarding_logger.info(f"Current server: {SERVER_ID} ({SERVER_IP}:{SERVER_PORT})")
    forwarding_logger.info(f"Data payload: {json.dumps({'test': 'data', 'timestamp': test_timestamp}, indent=2)}")
    forwarding_logger.info(f"=== TEST FORWARDING END ===")
    
    # Also log to main logger for comparison
    logger.info(f"Forwarding logger test completed at {test_timestamp}")
    
    return {
        "status": "test_completed",
        "timestamp": test_timestamp,
        "message": "Check the forwarding log file for test messages",
        "forwarding_log_file": forwarding_log_filepath,
        "main_log_file": log_filepath,
        "server_id": SERVER_ID
    }

@app.get("/ccs/ccs-websocket/health")
async def health_check():
    """Simple health check endpoint for load balancer and monitoring"""
    # Test forwarding logger on every health check
    forwarding_logger.info(f"💓 HEALTH CHECK - Forwarding logger test from {SERVER_ID}")
    
    # Basic health information
    active_sessions_count = await session_manager.get_session_count()
    local_session_count = session_manager.get_local_session_count()
    elasticache_connected = session_manager.is_connected()
    
    logger.info(f"Health check - Cache sessions: {active_sessions_count}, Local sessions: {local_session_count}, Cache connected: {elasticache_connected}")
    
    return {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
        "server_id": SERVER_ID,
        "sessions": {
            "cache_sessions": active_sessions_count,
            "local_sessions": local_session_count
        },
        "cache_connected": elasticache_connected
    }

@app.get("/ccs/ccs-websocket/detailed")
async def detailed_diagnostics():
    """Comprehensive diagnostics including cache, sessions, and legacy storage"""
    try:
        # Get active sessions from ElastiCache
        active_sessions_count = await session_manager.get_session_count()
        connection_states_data = await session_manager.get_all_sessions("connection_states")
        session_ids_list = list(connection_states_data.keys())
        
        # Also check local WebSocket connections
        local_session_count = session_manager.get_local_session_count()
        local_sessions = session_manager.get_all_websocket_sessions()
        
        # Get detailed cache usage statistics
        cache_stats = {}
        cache_detailed_info = {}
        
        # Check ElastiCache connection health
        elasticache_healthy = await session_manager.health_check()
        
        if session_manager.is_connected():
            try:
                # Get info from Redis
                cache_stats = {
                    "connection_status": "connected",
                    "host": session_manager.elasticache_host,
                    "port": session_manager.elasticache_port,
                    "password_configured": session_manager.elasticache_password is not None,
                    "health_check": elasticache_healthy
                }
                
                # Get all different session data types from cache
                environments_data = await session_manager.get_all_sessions("session_environments")
                tokens_data = await session_manager.get_all_sessions("session_tokens")
                secrets_data = await session_manager.get_all_sessions("session_secrets")
                uisources_data = await session_manager.get_all_sessions("session_uisources")
                ping_times_data = await session_manager.get_all_sessions("last_ping_time")
                metadata_data = await session_manager.get_all_sessions("connection_metadata")
                
                cache_detailed_info = {
                    "connection_states": {
                        "count": len(connection_states_data),
                        "sessions": list(connection_states_data.keys())
                    },
                    "session_environments": {
                        "count": len(environments_data),
                        "sessions": list(environments_data.keys())
                    },
                    "session_tokens": {
                        "count": len(tokens_data),
                        "sessions": list(tokens_data.keys())
                    },
                    "session_secrets": {
                        "count": len(secrets_data),
                        "sessions": list(secrets_data.keys())
                    },
                    "session_uisources": {
                        "count": len(uisources_data),
                        "sessions": list(uisources_data.keys())
                    },
                    "last_ping_times": {
                        "count": len(ping_times_data),
                        "sessions": list(ping_times_data.keys())
                    },
                    "connection_metadata": {
                        "count": len(metadata_data),
                        "sessions": list(metadata_data.keys())
                    }
                }
                
                # Check for session data consistency
                all_cache_sessions = set()
                all_cache_sessions.update(connection_states_data.keys())
                all_cache_sessions.update(environments_data.keys())
                all_cache_sessions.update(tokens_data.keys())
                all_cache_sessions.update(secrets_data.keys())
                all_cache_sessions.update(uisources_data.keys())
                all_cache_sessions.update(ping_times_data.keys())
                all_cache_sessions.update(metadata_data.keys())
                
                cache_detailed_info["total_unique_sessions"] = len(all_cache_sessions)
                cache_detailed_info["all_cached_sessions"] = list(all_cache_sessions)
                
            except Exception as e:
                cache_stats = {
                    "connection_status": "error",
                    "error": str(e)
                }
                cache_detailed_info = {"error": "Failed to get cache details"}
        else:
            cache_stats = {
                "connection_status": "not_connected",
                "fallback_mode": "local_storage"
            }
            cache_detailed_info = {"info": "Using local fallback storage"}
        
        # Compare local vs cache sessions
        local_session_ids = set(local_sessions.keys())
        cache_session_ids = set(session_ids_list)
        
        session_comparison = {
            "local_only": list(local_session_ids - cache_session_ids),
            "cache_only": list(cache_session_ids - local_session_ids),
            "in_both": list(local_session_ids & cache_session_ids),
            "total_local": len(local_session_ids),
            "total_cache": len(cache_session_ids)
        }
        
        # Legacy storage check (for comparison during transition)
        legacy_sessions_count = len(sessions)
        legacy_connection_states_count = len(connection_states)
        legacy_ping_times_count = len(last_ping_time)
        legacy_environments_count = len(session_environments)
        legacy_tokens_count = len(session_tokens)
        legacy_secrets_count = len(session_secrets)
        legacy_uisources_count = len(session_uisources)
        
        legacy_info = {
            "sessions": legacy_sessions_count,
            "connection_states": legacy_connection_states_count,
            "last_ping_time": legacy_ping_times_count,
            "session_environments": legacy_environments_count,
            "session_tokens": legacy_tokens_count,
            "session_secrets": legacy_secrets_count,
            "session_uisources": legacy_uisources_count
        }
        
        logger.info(f"Detailed diagnostics - Cache status: {cache_stats.get('connection_status', 'unknown')}")
        
        return {
            "status": "healthy", 
            "timestamp": asyncio.get_event_loop().time(),
            "server_info": {
                "server_id": SERVER_ID,
                "server_ip": SERVER_IP,
                "server_port": SERVER_PORT
            },
            "elasticache": {
                "connected": session_manager.is_connected(),
                "sessions_count": active_sessions_count,
                "session_ids": session_ids_list,
                "cache_stats": cache_stats,
                "detailed_cache_info": cache_detailed_info
            },
            "local_websockets": {
                "sessions_count": local_session_count,
                "session_ids": list(local_sessions.keys())
            },
            "session_comparison": session_comparison,
            "legacy_storage": legacy_info,
            "diagnostics": {
                "cache_usage_active": session_manager.is_connected(),
                "session_data_synchronized": len(session_comparison["local_only"]) == 0 and len(session_comparison["cache_only"]) == 0,
                "cache_health": elasticache_healthy if session_manager.is_connected() else None
            }
        }
    except Exception as e:
        logger.error(f"Detailed diagnostics error: {str(e)}")
        return {
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

@app.get("/ccs/ccs-websocket/sessions")
async def get_sessions():
    """Get information about active sessions"""
    current_time = asyncio.get_event_loop().time()
    session_info = {}
    
    # Get data from ElastiCache
    connection_states_data = await session_manager.get_all_sessions("connection_states")
    last_ping_data = await session_manager.get_all_sessions("last_ping_time")
    local_sessions = session_manager.get_all_websocket_sessions()
    
    for session_id in connection_states_data.keys():
        last_ping = last_ping_data.get(session_id, 0)
        has_websocket = session_id in local_sessions
        websocket_state = None
        
        if has_websocket:
            try:
                websocket_state = local_sessions[session_id].client_state.value
            except:
                websocket_state = "unknown"
        
        session_info[session_id] = {
            "connected": connection_states_data.get(session_id, False),
            "last_ping_ago": current_time - last_ping if last_ping else None,
            "websocket_state": websocket_state,
            "has_local_websocket": has_websocket,
            "stored_in_elasticache": True
        }
    
    return session_info

@app.get("/ccs/ccs-websocket/debug/stale-sessions")
async def debug_stale_sessions():
    """Identify and optionally clean up stale session metadata"""
    try:
        result = {
            "timestamp": asyncio.get_event_loop().time(),
            "server_info": {
                "server_id": SERVER_ID,
                "server_ip": SERVER_IP,
                "server_port": SERVER_PORT
            },
            "stale_sessions": [],
            "analysis": {
                "total_sessions_in_cache": 0,
                "local_websocket_sessions": 0,
                "stale_sessions_count": 0
            }
        }
        
        if not session_manager.is_connected():
            return {
                "error": "Cache not connected",
                "timestamp": asyncio.get_event_loop().time()
            }
        
        # Get all sessions from cache
        connection_states = await session_manager.get_all_sessions("connection_states")
        metadata_sessions = await session_manager.get_all_sessions("connection_metadata")
        
        # Get local WebSocket sessions
        local_sessions = session_manager.get_all_websocket_sessions()
        
        result["analysis"]["total_sessions_in_cache"] = len(connection_states)
        result["analysis"]["local_websocket_sessions"] = len(local_sessions)
        
        # Check each session in metadata to see if it claims to be on this server but doesn't have a local WebSocket
        for session_id, metadata in metadata_sessions.items():
            if isinstance(metadata, dict) and metadata.get("server_id") == SERVER_ID:
                # This session claims to be on this server
                has_local_websocket = session_id in local_sessions
                
                if not has_local_websocket:
                    # Stale session found!
                    connection_state = connection_states.get(session_id, False)
                    result["stale_sessions"].append({
                        "session_id": session_id,
                        "metadata": metadata,
                        "connection_state": connection_state,
                        "has_local_websocket": False,
                        "connected_at": metadata.get("connected_at", "unknown")
                    })
        
        result["analysis"]["stale_sessions_count"] = len(result["stale_sessions"])
        
        return result
        
    except Exception as e:
        logger.error(f"Debug stale sessions error: {str(e)}")
        return {
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

@app.post("/ccs/ccs-websocket/debug/cleanup-stale")
async def cleanup_stale_sessions_endpoint():
    """Clean up all detected stale sessions"""
    try:
        result = {
            "timestamp": asyncio.get_event_loop().time(),
            "server_id": SERVER_ID,
            "cleaned_sessions": [],
            "errors": []
        }
        
        if not session_manager.is_connected():
            return {
                "error": "Cache not connected",
                "timestamp": asyncio.get_event_loop().time()
            }
        
        # Get stale sessions first
        metadata_sessions = await session_manager.get_all_sessions("connection_metadata")
        local_sessions = session_manager.get_all_websocket_sessions()
        
        # Find and clean stale sessions
        for session_id, metadata in metadata_sessions.items():
            if isinstance(metadata, dict) and metadata.get("server_id") == SERVER_ID:
                has_local_websocket = session_id in local_sessions
                
                if not has_local_websocket:
                    try:
                        logger.info(f"Cleaning up stale session: {session_id}")
                        await session_manager.cleanup_session(session_id)
                        result["cleaned_sessions"].append(session_id)
                    except Exception as e:
                        logger.error(f"Failed to cleanup session {session_id}: {str(e)}")
                        result["errors"].append({
                            "session_id": session_id,
                            "error": str(e)
                        })
        
        logger.info(f"Cleaned up {len(result['cleaned_sessions'])} stale sessions")
        return result
        
    except Exception as e:
        logger.error(f"Cleanup stale sessions error: {str(e)}")
        return {
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

@app.get("/ccs/ccs-websocket/cache/diagnostics")
async def cache_diagnostics():
    """Detailed cache diagnostics and usage statistics"""
    try:
        # Get comprehensive cache information
        cache_info = await session_manager.get_cache_info()
        session_stats = await session_manager.get_session_statistics()
        
        # Test cache operations
        cache_operations_test = {}
        if session_manager.is_connected():
            try:
                # Test write operation
                test_key = "diagnostic_test"
                test_data = {"timestamp": asyncio.get_event_loop().time(), "test": "cache_write"}
                await session_manager.set_session_data("test_session", test_key, test_data)
                
                # Test read operation
                retrieved_data = await session_manager.get_session_data("test_session", test_key)
                
                # Test delete operation
                await session_manager.remove_session_data("test_session", test_key)
                
                cache_operations_test = {
                    "write_test": "success",
                    "read_test": "success" if retrieved_data == test_data else "failed",
                    "delete_test": "success",
                    "read_after_delete": "success" if await session_manager.get_session_data("test_session", test_key) is None else "failed"
                }
            except Exception as e:
                cache_operations_test = {
                    "error": str(e)
                }
        else:
            cache_operations_test = {
                "status": "cache_not_connected"
            }
        
        # Check if sessions are actually using cache vs legacy storage
        usage_analysis = {
            "cache_used_for_new_sessions": session_manager.is_connected(),
            "fallback_mode_active": not session_manager.is_connected(),
            "session_data_sources": {}
        }
        
        # Analyze where session data is being retrieved from
        if session_manager.is_connected():
            try:
                # Test if we can retrieve a real session from cache
                connection_states = await session_manager.get_all_sessions("connection_states")
                if connection_states:
                    sample_session = list(connection_states.keys())[0]
                    cache_data = await session_manager.get_session_data(sample_session, "connection_states")
                    legacy_data = connection_states.get(sample_session)  # This would be from legacy storage
                    
                    usage_analysis["session_data_sources"] = {
                        "sample_session": sample_session,
                        "cache_data_available": cache_data is not None,
                        "legacy_data_available": legacy_data is not None,
                        "data_match": cache_data == legacy_data if cache_data is not None and legacy_data is not None else False
                    }
            except Exception as e:
                usage_analysis["session_data_sources"] = {"error": str(e)}
        
        return {
            "timestamp": asyncio.get_event_loop().time(),
            "cache_connection": cache_info,
            "session_statistics": session_stats,
            "cache_operations_test": cache_operations_test,
            "usage_analysis": usage_analysis,
            "recommendations": get_cache_recommendations(cache_info, session_stats)
        }
    
    except Exception as e:
        logger.error(f"Cache diagnostics error: {str(e)}")
        return {
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

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
        local_websocket = session_manager.get_websocket_connection(session_id)
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

def get_cache_recommendations(cache_info: Dict[str, Any], session_stats: Dict[str, Any]) -> List[str]:
    """Generate recommendations based on cache diagnostics"""
    recommendations = []
    
    if not cache_info.get("connected", False):
        recommendations.append("⚠️  ElastiCache is not connected - sessions will not persist across server restarts")
        recommendations.append("🔧 Check ElastiCache endpoint, port, and authentication configuration")
    
    consistency = session_stats.get("consistency_check", {})
    if not consistency.get("is_consistent", True):
        recommendations.append("⚠️  Session data is not consistent between cache and local storage")
        if consistency.get("cache_only"):
            recommendations.append(f"📊 {len(consistency['cache_only'])} sessions exist only in cache: {consistency['cache_only']}")
        if consistency.get("local_only"):
            recommendations.append(f"📊 {len(consistency['local_only'])} sessions exist only locally: {consistency['local_only']}")
    
    hit_ratio = cache_info.get("cache_hit_ratio", 0)
    if hit_ratio < 0.8 and cache_info.get("connected", False):
        recommendations.append(f"📈 Cache hit ratio is {hit_ratio:.2%} - consider increasing cache TTL or checking access patterns")
    
    app_keys = cache_info.get("application_keys_count", 0)
    if app_keys == 0 and cache_info.get("connected", False):
        recommendations.append("❗ No application keys found in cache - sessions may not be persisting")
    
    return recommendations

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
        target_session = session_manager.get_websocket_connection(session_id)
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
