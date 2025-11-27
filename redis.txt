"""
AWS ElastiCache Session Manager for WebSocket Connections

This module provides a distributed session management solution using AWS ElastiCache (Redis)
for managing WebSocket sessions across multiple server instances behind an Application Load Balancer.

Key Features:
- Distributed session storage with ElastiCache
- Cross-instance WebSocket connection tracking
- Connection metadata for server-to-server communication
- Fallback to local storage when ElastiCache is unavailable
- Automatic TTL management for session data
- Pickle serialization for complex data types

Author: CCS Team
Date: 2024
"""

import asyncio
import pickle
import logging
import os
import boto3
import requests
import time
from typing import Dict, Any, Optional
import redis.asyncio as async_redis
from fastapi import WebSocket
from botocore.exceptions import BotoCoreError, NoCredentialsError, PartialCredentialsError
from contextlib import asynccontextmanager

def get_ec2_region(logger=None):
    """
    Auto-detect AWS region from EC2 instance metadata.
    
    Args:
        logger: Logger instance for logging messages
        
    Returns:
        str: AWS region name, defaults to 'us-west-2' if detection fails
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        
    try:
        # Get IMDSv2 token
        token_url = "http://169.254.169.254/latest/api/token"
        token_headers = {"X-aws-ec2-metadata-token-ttl-seconds": "21600"}
        token_response = requests.put(token_url, headers=token_headers, timeout=2)
        
        if token_response.status_code == 200:
            token = token_response.text
            
            # Get instance identity document
            metadata_url = "http://169.254.169.254/latest/dynamic/instance-identity/document"
            metadata_headers = {"X-aws-ec2-metadata-token": token}
            metadata_response = requests.get(metadata_url, headers=metadata_headers, timeout=2)
            
            if metadata_response.status_code == 200:
                instance_data = metadata_response.json()
                region = instance_data.get('region')
                if region:
                    logger.info(f"✅ Auto-detected AWS region from EC2 metadata: {region}")
                    return region
        
        # Fallback if IMDSv2 fails - try IMDSv1
        metadata_url = "http://169.254.169.254/latest/dynamic/instance-identity/document"
        metadata_response = requests.get(metadata_url, timeout=2)
        if metadata_response.status_code == 200:
            instance_data = metadata_response.json()
            region = instance_data.get('region')
            if region:
                logger.info(f"✅ Auto-detected AWS region from EC2 metadata (IMDSv1): {region}")
                return region
                
    except Exception as e:
        logger.warning(f"⚠️  Could not auto-detect region from EC2 metadata: {str(e)}")
        logger.info(f"   Falling back to default region: us-west-2")
    
    # Default fallback
    return "us-west-2"

def create_ssm_client(logger=None):
    """
    Creates a boto3 client for SSM service.
    
    Args:
        logger: Logger instance for logging messages

    Returns:
        boto3.client : A boto3 SSM client object
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        
    try:
        # For ElastiCache, use us-west-2 since that's where the cluster is
        region = get_ec2_region(logger)
        
        logger.info(f"Using AWS region for SSM: {region}")
        
        logger.debug("Creating boto3 client for SSM")
        ssm_client = boto3.client('ssm', region)
        logger.debug(f"SSM client created successfully")
        return ssm_client
    except (BotoCoreError, NoCredentialsError, PartialCredentialsError) as e:
        logger.error(f"Failed to create boto3 client: {e}")
        raise
    except ValueError as e:
        logger.error(f"Value error: {e}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise

class CircuitBreaker:
    """
    Circuit breaker pattern implementation for ElastiCache connections
    Prevents cascading failures by temporarily stopping failed operations
    """
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60, logger=None):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.logger = logger or logging.getLogger(__name__)
    
    def can_execute(self) -> bool:
        """Check if operation can be executed based on circuit breaker state"""
        if self.state == "CLOSED":
            return True
        elif self.state == "OPEN":
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = "HALF_OPEN"
                self.logger.info("🔄 Circuit breaker: OPEN -> HALF_OPEN")
                return True
            return False
        elif self.state == "HALF_OPEN":
            return True
        return False
    
    def record_success(self):
        """Record successful operation"""
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            self.logger.info("✅ Circuit breaker: HALF_OPEN -> CLOSED")
    
    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold and self.state == "CLOSED":
            self.state = "OPEN"
            self.logger.warning(f"❌ Circuit breaker: CLOSED -> OPEN (failures: {self.failure_count})")
        elif self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.logger.warning("❌ Circuit breaker: HALF_OPEN -> OPEN")

def get_elasticache_secret(logger=None):
    """
    Fetch ElastiCache secret from AWS SSM Parameter Store
    
    Args:
        logger: Logger instance for logging messages
    
    Returns:
        str: The ElastiCache secret key or None if failed
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        
    try:
        ssm_client = create_ssm_client(logger)
        
        # Fetch the ElastiCache secret from SSM Parameter Store
        response = ssm_client.get_parameters(
            Names=[
                '/H9VV/CCS/ElastiCache/secret',  # ElastiCache secret parameter
            ],
            WithDecryption=True
        )
        logger.debug(f"SSM response received")
        
        # Extract the secret value
        parameters = response.get('Parameters', [])
        for param in parameters:
            if param['Name'] == '/H9VV/CCS/ElastiCache/secret':
                logger.info(f"✅ ElastiCache secret retrieved from SSM successfully")
                secret_value = param['Value']
                logger.debug(f"Secret retrieved: {secret_value[:10]}...")  # Only show first 10 chars for security
                return secret_value
        
        logger.error("❌ ElastiCache secret not found in SSM response")
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch ElastiCache secret from SSM: {e}")
        return None

class ElastiCacheSessionManager:
    """
    Robust WebSocket session manager using AWS ElastiCache with advanced reliability features
    
    Features:
    - Async Redis operations with connection pooling
    - Circuit breaker pattern for failure resilience
    - Automatic retry logic with exponential backoff
    - Connection health monitoring and recovery
    - Efficient batch operations
    - Graceful fallback to local storage
    - Memory-efficient local cache with TTL
    """
    
    def __init__(self, elasticache_host: Optional[str] = None, 
                 elasticache_port: int = 6379, elasticache_password: Optional[str] = None,
                 logger=None):
        """
        Initialize ElastiCache Session Manager with robust connection handling
        """
        self.elasticache_host = elasticache_host or "localhost"
        self.elasticache_port = elasticache_port
        self.logger = logger or logging.getLogger(__name__)
        
        # Get password from SSM or use provided
        if elasticache_password:
            self.elasticache_password = elasticache_password
            self.logger.info("Using provided ElastiCache password")
        else:
            self.logger.info("Fetching ElastiCache password from SSM...")
            self.elasticache_password = get_elasticache_secret(self.logger)
            if self.elasticache_password:
                self.logger.info("✅ ElastiCache password retrieved from SSM")
            else:
                self.logger.warning("⚠️  Failed to retrieve ElastiCache password from SSM")
        
        # Connection management
        self.connection_pool = None
        self.elasticache_client = None
        self._connection_lock = asyncio.Lock()
        self._last_health_check = 0
        self._health_check_interval = 30  # seconds
        
        # Circuit breaker for resilience
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            timeout=30,
            logger=self.logger
        )
        
        # Local cache with TTL for fallback
        self.local_sessions = {}
        self._local_cache_ttl = {}  # Track TTL for local cache cleanup
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes
        
        # Redis key prefixes
        self.KEY_PREFIXES = {
            'connection_states': 'ws:conn',
            'last_ping_time': 'ws:ping', 
            'session_environments': 'ws:env',
            'session_tokens': 'ws:token',
            'session_secrets': 'ws:secret',
            'session_uisources': 'ws:ui',
            'connection_metadata': 'ws:meta'
        }
        
        # Session expiration time (2 hours)
        self.SESSION_EXPIRE_TIME = 7200
        
        # Retry configuration
        self.MAX_RETRIES = 3
        self.BASE_DELAY = 0.1  # 100ms base delay
        self.MAX_DELAY = 2.0   # 2 second max delay
    
    async def connect(self) -> bool:
        """
        Establish robust connection to ElastiCache with Redis cluster support
        """
        async with self._connection_lock:
            try:
                # Try Redis cluster client first for ElastiCache cluster mode
                try:
                    from redis.asyncio.cluster import RedisCluster
                    
                    # Use Redis Cluster client for cluster mode ElastiCache
                    self.elasticache_client = RedisCluster(
                        host=self.elasticache_host,
                        port=self.elasticache_port,
                        password=self.elasticache_password,
                        ssl=True,  # Enable SSL for cluster
                        ssl_cert_reqs=None,
                        ssl_check_hostname=False,
                        socket_keepalive=True,
                        socket_keepalive_options={},
                        health_check_interval=30,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                        decode_responses=False,
                        max_connections_per_node=10,  # Connections per cluster node
                        skip_full_coverage_check=True,  # Allow partial cluster discovery
                        cluster_error_retry_attempts=3
                    )
                    self.logger.info("Using Redis Cluster client for ElastiCache cluster mode")
                    
                except ImportError:
                    # Fallback to regular Redis client if cluster not available
                    self.elasticache_client = async_redis.Redis(
                        host=self.elasticache_host,
                        port=self.elasticache_port,
                        password=self.elasticache_password,
                        ssl=True,  # Enable SSL for async Redis
                        ssl_cert_reqs=None,
                        ssl_check_hostname=False,
                        socket_keepalive=True,
                        socket_keepalive_options={},
                        health_check_interval=30,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                        decode_responses=False,
                        max_connections=50
                    )
                    self.logger.info("Using regular Redis client (cluster client not available)")
                
                # Test connection with timeout
                await asyncio.wait_for(self.elasticache_client.ping(), timeout=5)
                
                # Reset circuit breaker on successful connection
                self.circuit_breaker.record_success()
                
                client_type = "Redis Cluster" if hasattr(self.elasticache_client, 'get_node') else "Regular Redis"
                self.logger.info(f"✅ ElastiCache {client_type} connected to {self.elasticache_host}:{self.elasticache_port}")
                self.logger.info(f"   SSL: enabled, Health check: 30s")
                return True
                
            except asyncio.TimeoutError:
                self.logger.error(f"❌ ElastiCache connection timeout to {self.elasticache_host}:{self.elasticache_port}")
                self.circuit_breaker.record_failure()
                await self._cleanup_failed_connection()
                return False
            except Exception as e:
                self.logger.error(f"❌ Failed to connect to ElastiCache: {str(e)}")
                self.circuit_breaker.record_failure()
                await self._cleanup_failed_connection()
                return False
    
    async def _cleanup_failed_connection(self):
        """Clean up failed connection resources"""
        if self.elasticache_client:
            try:
                # Handle both Redis and RedisCluster client types
                if hasattr(self.elasticache_client, 'close'):
                    await self.elasticache_client.close()
                else:
                    await self.elasticache_client.aclose()
            except Exception:
                pass
        self.elasticache_client = None
        self.connection_pool = None
        self.logger.warning("🔄 Falling back to local storage after connection failure")
    
    async def _retry_with_backoff(self, operation, *args, **kwargs):
        """Execute operation with exponential backoff retry"""
        last_exception = None
        
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # Check circuit breaker
                if not self.circuit_breaker.can_execute():
                    raise Exception("Circuit breaker is OPEN")
                
                # Execute operation
                result = await operation(*args, **kwargs)
                
                # Success - reset circuit breaker
                if attempt > 0:  # Only log if we had to retry
                    self.logger.info(f"✅ Operation succeeded after {attempt} retries")
                self.circuit_breaker.record_success()
                return result
                
            except Exception as e:
                last_exception = e
                
                if attempt < self.MAX_RETRIES:
                    # Calculate delay with exponential backoff + jitter
                    delay = min(self.BASE_DELAY * (2 ** attempt), self.MAX_DELAY)
                    jitter = delay * 0.1 * (0.5 - hash(str(e)) % 100 / 100)  # -10% to +10%
                    total_delay = delay + jitter
                    
                    self.logger.warning(f"⚠️  Attempt {attempt + 1} failed: {str(e)[:100]}, retrying in {total_delay:.2f}s")
                    await asyncio.sleep(total_delay)
                else:
                    # Final attempt failed
                    self.circuit_breaker.record_failure()
                    self.logger.error(f"❌ All {self.MAX_RETRIES + 1} attempts failed: {str(e)}")
        
        raise last_exception
    
    async def _auto_reconnect(self) -> bool:
        """Attempt to reconnect if connection is lost"""
        if not self.is_connected():
            self.logger.info("🔄 Attempting auto-reconnection to ElastiCache...")
            return await self.connect()
        return True
    
    def _cleanup_local_cache(self):
        """Clean up expired entries from local cache"""
        if time.time() - self._last_cleanup < self._cleanup_interval:
            return
        
        current_time = time.time()
        expired_keys = []
        
        # Check TTL for all cached items
        for cache_key, expire_time in self._local_cache_ttl.items():
            if current_time > expire_time:
                expired_keys.append(cache_key)
        
        # Remove expired items
        for cache_key in expired_keys:
            self._remove_from_local_cache(cache_key)
        
        if expired_keys:
            self.logger.debug(f"🧹 Cleaned up {len(expired_keys)} expired local cache entries")
        
        self._last_cleanup = current_time
    
    def _set_local_cache(self, key: str, value: Any, ttl: int = None):
        """Set item in local cache with TTL"""
        self.local_sessions[key] = value
        if ttl:
            self._local_cache_ttl[key] = time.time() + ttl
        self._cleanup_local_cache()
    
    def _get_local_cache(self, key: str, default=None):
        """Get item from local cache"""
        self._cleanup_local_cache()
        return self.local_sessions.get(key, default)
    
    def _remove_from_local_cache(self, key: str):
        """Remove item from local cache"""
        self.local_sessions.pop(key, None)
        self._local_cache_ttl.pop(key, None)
    
    async def disconnect(self):
        """Close ElastiCache connection gracefully"""
        async with self._connection_lock:
            if self.elasticache_client:
                try:
                    # Handle both Redis and RedisCluster client types
                    if hasattr(self.elasticache_client, 'close'):
                        await self.elasticache_client.close()
                    else:
                        await self.elasticache_client.aclose()
                except Exception:
                    pass
            
            self.elasticache_client = None
            self.connection_pool = None
            self.logger.info("✅ ElastiCache connection closed gracefully")
    
    async def health_check(self) -> bool:
        """
        Comprehensive health check with connection recovery
        """
        current_time = time.time()
        
        # Rate limit health checks
        if current_time - self._last_health_check < self._health_check_interval:
            return self.is_connected()
        
        self._last_health_check = current_time
        
        if not self.elasticache_client:
            return False
        
        try:
            # Test with timeout
            await asyncio.wait_for(self.elasticache_client.ping(), timeout=3)
            
            # Test set/get operation
            test_key = f"health_check_{int(current_time)}"
            await asyncio.wait_for(
                self.elasticache_client.setex(test_key, 10, b"test"), 
                timeout=2
            )
            result = await asyncio.wait_for(
                self.elasticache_client.get(test_key), 
                timeout=2
            )
            await self.elasticache_client.delete(test_key)
            
            if result == b"test":
                self.circuit_breaker.record_success()
                return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Health check failed: {str(e)[:100]}")
            self.circuit_breaker.record_failure()
            
            # Attempt reconnection if health check fails
            await self._auto_reconnect()
            return False
    
    async def set_session_data(self, session_id: str, key_type: str, value: Any):
        """
        Store session data with robust error handling and fallback
        """
        if not self.circuit_breaker.can_execute():
            self.logger.debug(f"Circuit breaker OPEN, using local storage for {key_type}:{session_id}")
            cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
            self._set_local_cache(cache_key, value, self.SESSION_EXPIRE_TIME)
            return
        
        async def _set_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
            serialized_value = pickle.dumps(value)
            
            await self.elasticache_client.setex(
                cache_key, 
                self.SESSION_EXPIRE_TIME, 
                serialized_value
            )
        
        try:
            await self._retry_with_backoff(_set_operation)
            self.logger.debug(f"✅ Cache SET: {key_type}:{session_id}")
        except Exception as e:
            # Fallback to local storage
            self.logger.debug(f"💾 Local fallback SET: {key_type}:{session_id}")
            cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
            self._set_local_cache(cache_key, value, self.SESSION_EXPIRE_TIME)
    
    async def get_session_data(self, session_id: str, key_type: str, default=None):
        """
        Retrieve session data with robust error handling and fallback
        """
        cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
        
        # Check local cache first if circuit breaker is open
        if not self.circuit_breaker.can_execute():
            self.logger.debug(f"Circuit breaker OPEN, checking local cache for {key_type}:{session_id}")
            return self._get_local_cache(cache_key, default)
        
        async def _get_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            serialized_value = await self.elasticache_client.get(cache_key)
            if serialized_value:
                return pickle.loads(serialized_value)
            return default
        
        try:
            result = await self._retry_with_backoff(_get_operation)
            self.logger.debug(f"✅ Cache GET: {key_type}:{session_id} {'(found)' if result != default else '(not found)'}")
            return result
        except Exception as e:
            # Fallback to local storage
            self.logger.debug(f"💾 Local fallback GET: {key_type}:{session_id}")
            return self._get_local_cache(cache_key, default)
    
    async def set_session_batch(self, session_id: str, data_dict: Dict[str, Any]):
        """
        Set multiple session data values efficiently for Redis cluster
        """
        if not self.circuit_breaker.can_execute():
            # Fallback to local storage
            for key_type, value in data_dict.items():
                cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
                self._set_local_cache(cache_key, value, self.SESSION_EXPIRE_TIME)
            self.logger.debug(f"Circuit breaker OPEN, batch SET to local cache for session {session_id}")
            return
        
        async def _batch_set_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            # For Redis cluster, use individual operations instead of pipeline
            # This avoids cross-slot pipeline issues in cluster mode
            for key_type, value in data_dict.items():
                cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
                serialized_value = pickle.dumps(value)
                await self.elasticache_client.setex(cache_key, self.SESSION_EXPIRE_TIME, serialized_value)
        
        try:
            await self._retry_with_backoff(_batch_set_operation)
            self.logger.debug(f"✅ Cluster batch SET ({len(data_dict)} items) for session {session_id}")
        except Exception as e:
            # Fallback to local storage
            for key_type, value in data_dict.items():
                cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
                self._set_local_cache(cache_key, value, self.SESSION_EXPIRE_TIME)
            self.logger.debug(f"💾 Batch fallback SET for session {session_id}")
    
    async def get_session_batch(self, session_id: str, key_types: list) -> Dict[str, Any]:
        """
        Get multiple session data values efficiently for Redis cluster
        """
        result = {}
        
        if not self.circuit_breaker.can_execute():
            # Fallback to local storage
            for key_type in key_types:
                cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
                result[key_type] = self._get_local_cache(cache_key)
            return result
        
        async def _batch_get_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            # For Redis cluster, use individual operations to avoid cross-slot issues
            batch_result = {}
            for key_type in key_types:
                cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
                serialized_value = await self.elasticache_client.get(cache_key)
                if serialized_value:
                    batch_result[key_type] = pickle.loads(serialized_value)
                else:
                    batch_result[key_type] = None
            return batch_result
        
        try:
            result = await self._retry_with_backoff(_batch_get_operation)
            self.logger.debug(f"✅ Cluster batch GET ({len(key_types)} items) for session {session_id}")
            return result
        except Exception as e:
            # Fallback to local storage
            for key_type in key_types:
                cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
                result[key_type] = self._get_local_cache(cache_key)
            self.logger.debug(f"💾 Batch fallback GET for session {session_id}")
            return result
    async def remove_session_data(self, session_id: str, key_type: str):
        """
        Remove session data with proper async handling
        """
        cache_key = f"{self.KEY_PREFIXES.get(key_type, key_type)}:{session_id}"
        
        if not self.circuit_breaker.can_execute():
            self._remove_from_local_cache(cache_key)
            return
        
        async def _delete_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            await self.elasticache_client.delete(cache_key)
        
        try:
            await self._retry_with_backoff(_delete_operation)
            self.logger.debug(f"✅ Cache DELETE: {key_type}:{session_id}")
        except Exception as e:
            self.logger.debug(f"💾 Fallback DELETE: {key_type}:{session_id}")
        
        # Always clean from local cache too
        self._remove_from_local_cache(cache_key)
    
    async def get_all_sessions(self, key_type: str) -> Dict[str, Any]:
        """
        Retrieve all sessions of a specific type using efficient SCAN operation
        """
        if not self.circuit_breaker.can_execute():
            # Fallback to local storage
            prefix = self.KEY_PREFIXES.get(key_type, key_type)
            result = {}
            for cache_key, value in self.local_sessions.items():
                if cache_key.startswith(f"{prefix}:"):
                    session_id = cache_key.split(':', 1)[1]
                    result[session_id] = value
            return result
        
        async def _scan_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            prefix = self.KEY_PREFIXES.get(key_type, key_type)
            pattern = f"{prefix}:*"
            result = {}
            
            # Use SCAN instead of KEYS for better performance
            async for key in self.elasticache_client.scan_iter(match=pattern, count=100):
                try:
                    if isinstance(key, bytes):
                        key_str = key.decode('utf-8')
                    else:
                        key_str = key
                    
                    session_id = key_str.split(':', 1)[1]
                    serialized_value = await self.elasticache_client.get(key)
                    
                    if serialized_value:
                        result[session_id] = pickle.loads(serialized_value)
                except Exception as e:
                    self.logger.warning(f"Error processing key {key}: {e}")
                    continue
            
            return result
        
        try:
            result = await self._retry_with_backoff(_scan_operation)
            self.logger.debug(f"✅ Scan ALL {key_type}: {len(result)} sessions")
            return result
        except Exception as e:
            self.logger.debug(f"💾 Fallback scan ALL {key_type}")
            # Fallback to local storage
            prefix = self.KEY_PREFIXES.get(key_type, key_type)
            result = {}
            for cache_key, value in self.local_sessions.items():
                if cache_key.startswith(f"{prefix}:"):
                    session_id = cache_key.split(':', 1)[1]
                    result[session_id] = value
            return result
    
    def add_websocket_connection(self, session_id: str, websocket: WebSocket):
        """
        Add WebSocket connection to local cache with automatic cleanup
        """
        # Store websocket with special prefix
        websocket_key = f"websocket_conn:{session_id}"
        self.local_sessions[websocket_key] = websocket
        self.logger.debug(f"➕ Added WebSocket connection for session {session_id}")
    
    def get_websocket_connection(self, session_id: str) -> Optional[WebSocket]:
        """
        Retrieve WebSocket connection from local cache
        """
        websocket_key = f"websocket_conn:{session_id}"
        return self.local_sessions.get(websocket_key)
    
    def remove_websocket_connection(self, session_id: str):
        """
        Remove WebSocket connection from local cache
        """
        websocket_key = f"websocket_conn:{session_id}"
        if websocket_key in self.local_sessions:
            del self.local_sessions[websocket_key]
            self.logger.debug(f"➖ Removed WebSocket connection for session {session_id}")
    
    def get_all_websocket_sessions(self) -> Dict[str, WebSocket]:
        """
        Get all local WebSocket sessions
        """
        result = {}
        for cache_key, websocket in self.local_sessions.items():
            if cache_key.startswith("websocket_conn:") and isinstance(websocket, WebSocket):
                session_id = cache_key.split(':', 1)[1]
                result[session_id] = websocket
        return result
    
    async def set_connection_metadata(self, session_id: str, server_ip: str, server_port: int, server_id: str):
        """
        Store connection metadata with efficient async operation
        """
        metadata = {
            "server_ip": server_ip,
            "server_port": server_port,
            "server_id": server_id,
            "connected_at": time.time()
        }
        await self.set_session_data(session_id, "connection_metadata", metadata)
        self.logger.debug(f"✅ Set connection metadata for {session_id} on {server_id}")
    
    async def get_connection_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get connection metadata with efficient async operation
        """
        return await self.get_session_data(session_id, "connection_metadata")
    
    async def remove_connection_metadata(self, session_id: str):
        """
        Remove connection metadata with efficient async operation
        """
        await self.remove_session_data(session_id, "connection_metadata")
    

    
    async def cleanup_session(self, session_id: str):
        """
        Efficient batch cleanup of all session data
        """
        if not self.circuit_breaker.can_execute():
            # Clean local cache only
            for key_type in self.KEY_PREFIXES.keys():
                cache_key = f"{self.KEY_PREFIXES[key_type]}:{session_id}"
                self._remove_from_local_cache(cache_key)
            self.remove_websocket_connection(session_id)
            self.logger.debug(f"💾 Local cleanup for session {session_id}")
            return
        
        async def _batch_cleanup_operation():
            if not self.elasticache_client:
                raise Exception("ElastiCache client not available")
            
            # Batch delete all session-related keys
            cache_keys = [
                f"{self.KEY_PREFIXES[key_type]}:{session_id}" 
                for key_type in self.KEY_PREFIXES.keys()
            ]
            
            if cache_keys:
                await self.elasticache_client.delete(*cache_keys)
        
        try:
            await self._retry_with_backoff(_batch_cleanup_operation)
            self.logger.debug(f"✅ Batch cleanup for session {session_id}")
        except Exception as e:
            self.logger.debug(f"💾 Fallback cleanup for session {session_id}")
        
        # Always clean local cache
        for key_type in self.KEY_PREFIXES.keys():
            cache_key = f"{self.KEY_PREFIXES[key_type]}:{session_id}"
            self._remove_from_local_cache(cache_key)
        
        self.remove_websocket_connection(session_id)
        self.logger.info(f"🧹 Session cleanup completed: {session_id}")
    
    def is_connected(self) -> bool:
        """
        Check if ElastiCache cluster client is connected and healthy
        """
        return (
            self.elasticache_client is not None and 
            self.circuit_breaker.state != "OPEN"
        )
    
    async def get_session_count(self) -> int:
        """
        Get total count of active sessions efficiently
        """
        try:
            connection_states = await self.get_all_sessions("connection_states")
            return len(connection_states)
        except Exception:
            # Fallback to local count
            return len(self.get_all_websocket_sessions())
    
    def get_local_session_count(self) -> int:
        """
        Get count of local WebSocket sessions
        """
        return len(self.get_all_websocket_sessions())
    
    async def get_cache_info(self) -> Dict[str, Any]:
        """
        Get comprehensive cache information with performance metrics
        """
        info = {
            "connected": self.is_connected(),
            "host": self.elasticache_host,
            "port": self.elasticache_port,
            "password_configured": self.elasticache_password is not None,
            "circuit_breaker_state": self.circuit_breaker.state,
            "circuit_breaker_failures": self.circuit_breaker.failure_count,
            "async_client": True,  # Using async Redis client
            "max_connections": 50,
            "local_cache_entries": len(self.local_sessions)
        }
        
        if self.elasticache_client and self.circuit_breaker.can_execute():
            try:
                # Get Redis INFO with timeout
                redis_info = await asyncio.wait_for(
                    self.elasticache_client.info(), 
                    timeout=3
                )
                
                info.update({
                    "redis_version": redis_info.get("redis_version", "unknown"),
                    "connected_clients": redis_info.get("connected_clients", 0),
                    "used_memory_human": redis_info.get("used_memory_human", "0B"),
                    "keyspace_hits": redis_info.get("keyspace_hits", 0),
                    "keyspace_misses": redis_info.get("keyspace_misses", 0),
                    "total_commands_processed": redis_info.get("total_commands_processed", 0),
                })
                
                # Calculate hit ratio
                hits = redis_info.get("keyspace_hits", 0)
                misses = redis_info.get("keyspace_misses", 0)
                if hits + misses > 0:
                    info["cache_hit_ratio"] = round(hits / (hits + misses), 3)
                else:
                    info["cache_hit_ratio"] = 0
                
                # Count application keys efficiently
                app_keys = 0
                for prefix in self.KEY_PREFIXES.values():
                    pattern = f"{prefix}:*"
                    count = 0
                    async for _ in self.elasticache_client.scan_iter(match=pattern, count=100):
                        count += 1
                        if count >= 1000:  # Limit to prevent timeout
                            break
                    app_keys += count
                
                info["application_keys_count"] = app_keys
                
            except Exception as e:
                info["cache_info_error"] = str(e)
        
        return info
    
    async def get_session_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive session statistics with consistency analysis
        """
        stats = {
            "cache_sessions": {},
            "local_sessions": {},
            "consistency_check": {},
            "performance_metrics": {
                "circuit_breaker_state": self.circuit_breaker.state,
                "total_failures": self.circuit_breaker.failure_count,
                "last_health_check": self._last_health_check,
                "local_cache_size": len(self.local_sessions)
            }
        }
        
        # Get cache session counts by type (only if circuit breaker allows)
        if self.circuit_breaker.can_execute():
            for key_type in self.KEY_PREFIXES.keys():
                try:
                    sessions = await asyncio.wait_for(
                        self.get_all_sessions(key_type), 
                        timeout=5
                    )
                    stats["cache_sessions"][key_type] = {
                        "count": len(sessions),
                        "session_ids": list(sessions.keys())[:10]  # Limit for readability
                    }
                except Exception as e:
                    stats["cache_sessions"][key_type] = {
                        "error": str(e)[:100]
                    }
        
        # Get local session info
        local_websockets = self.get_all_websocket_sessions()
        stats["local_sessions"] = {
            "websocket_connections": {
                "count": len(local_websockets),
                "session_ids": list(local_websockets.keys())[:10]
            }
        }
        
        # Consistency check
        cache_sessions = stats["cache_sessions"].get("connection_states", {}).get("session_ids", [])
        local_sessions = list(local_websockets.keys())
        
        stats["consistency_check"] = {
            "cache_only": [sid for sid in cache_sessions if sid not in local_sessions][:5],
            "local_only": [sid for sid in local_sessions if sid not in cache_sessions][:5],
            "synchronized": [sid for sid in cache_sessions if sid in local_sessions][:5],
            "is_consistent": set(cache_sessions) == set(local_sessions),
            "cache_count": len(cache_sessions),
            "local_count": len(local_sessions)
        }
        
        return stats
    
    async def bulk_cleanup_stale_sessions(self, max_age_seconds: int = 7200) -> int:
        """
        Efficiently clean up stale sessions in bulk
        """
        if not self.circuit_breaker.can_execute():
            return 0
        
        current_time = time.time()
        stale_sessions = []
        
        try:
            # Get all sessions with last ping times
            ping_times = await self.get_all_sessions("last_ping_time")
            
            for session_id, last_ping in ping_times.items():
                if isinstance(last_ping, (int, float)):
                    if current_time - last_ping > max_age_seconds:
                        stale_sessions.append(session_id)
            
            # Bulk cleanup stale sessions
            if stale_sessions:
                cleanup_tasks = [
                    self.cleanup_session(session_id) 
                    for session_id in stale_sessions[:50]  # Limit batch size
                ]
                
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                
                self.logger.info(f"🧹 Bulk cleanup completed: {len(stale_sessions)} stale sessions")
            
            return len(stale_sessions)
            
        except Exception as e:
            self.logger.error(f"Bulk cleanup failed: {e}")
            return 0
