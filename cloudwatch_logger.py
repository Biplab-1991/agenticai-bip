"""
CloudWatch Logger Module

A reusable class for setting up CloudWatch logging with watchtower.
This module provides a modular way to configure CloudWatch logging for any service.

Usage:
    from cloudwatch_logger import CloudWatchLogger
    
    # Initialize logger
    cw_logger = CloudWatchLogger(
        log_group_name="/aws/ec2/my-service",
        service_name="my-service"
    )
    
    # Get the configured logger
    logger = cw_logger.get_logger()
    
    # Use it
    logger.info("Application started")
    logger.error("An error occurred")
"""

import logging
import os
import uuid
import boto3
import watchtower
import requests
from typing import Optional


class AutoFlushHandler(logging.Handler):
    """
    A logging handler wrapper that automatically flushes the underlying handler
    after each log record is emitted. This ensures logs are sent immediately to
    CloudWatch, preventing loss on crashes or infrequent logging.
    """
    
    def __init__(self, handler: logging.Handler):
        """
        Initialize the auto-flush handler wrapper.
        
        Args:
            handler: The underlying handler to wrap (e.g., CloudWatchLogHandler)
        """
        super().__init__()
        self.handler = handler
        self.setLevel(handler.level)
        self.setFormatter(handler.formatter)
    
    def emit(self, record: logging.LogRecord):
        """
        Emit a log record and immediately flush.
        
        Args:
            record: The log record to emit
        """
        try:
            # Emit the record to the underlying handler
            self.handler.emit(record)
            # Immediately flush to ensure it's sent to CloudWatch
            self.handler.flush()
        except Exception:
            self.handleError(record)
    
    def flush(self):
        """Flush the underlying handler."""
        if hasattr(self.handler, 'flush'):
            self.handler.flush()
    
    def close(self):
        """Close the underlying handler."""
        if hasattr(self.handler, 'close'):
            self.handler.close()
        super().close()


class CloudWatchLogger:
    """
    Reusable CloudWatch Logger class for centralized logging configuration.
    
    This class sets up logging to both CloudWatch and console, making it easy
    to use across different services with consistent configuration.
    
    Region auto-detection: If region is not provided or set to 'auto', 
    the class will automatically detect the region from EC2 instance metadata.
    """
    
    def __init__(
        self,
        log_group_name: str,
        service_name: str = "default-service",
        region: Optional[str] = None,
        log_level: int = logging.INFO,
        console_logging: bool = True,
        create_log_group: bool = True,
        use_queues: bool = True,
        send_interval: int = 5,
        max_batch_size: int = 100,
        max_batch_count: int = 10000,
        auto_flush: bool = True
    ):
        """
        Initialize CloudWatch Logger.
        
        Args:
            log_group_name (str): CloudWatch log group name (required).
            service_name (str): Name of the service for log identification
            region (str, optional): AWS region. If None or 'auto', will auto-detect from EC2 metadata.
                                   Falls back to 'us-east-1' if detection fails.
            log_level (int): Logging level (logging.INFO, logging.DEBUG, etc.)
            console_logging (bool): Whether to also log to console
            create_log_group (bool): Whether to create log group if it doesn't exist
            use_queues (bool): Use queues for better performance
            send_interval (int): Send logs every N seconds
            max_batch_size (int): Batch up to N log messages
            max_batch_count (int): Maximum messages to queue
            auto_flush (bool): If True, automatically flush logs immediately after each log call.
                              This ensures logs are sent to CloudWatch immediately, preventing loss
                              on crashes or infrequent logging. Recommended for critical logs.
        """
        self.log_group_name = log_group_name
        self.service_name = service_name
        self.log_level = log_level
        self.console_logging = console_logging
        self.create_log_group = create_log_group
        self.use_queues = use_queues
        self.send_interval = send_interval
        self.max_batch_size = max_batch_size
        self.max_batch_count = max_batch_count
        self.auto_flush = auto_flush
        
        # Auto-detect region if not provided or set to 'auto'
        if not region or region.lower() == 'auto':
            self.region = self._get_ec2_region()
        else:
            self.region = region
        
        # Generate log stream name: service-name-uuid-processid
        unique_id = str(uuid.uuid4())[:8]  # Use first 8 chars of UUID
        self.log_stream_name = f"{service_name}-{unique_id}-{os.getpid()}"
        
        # Initialize logger
        self.logger = None
        self.cloudwatch_enabled = False
        self.cloudwatch_handler = None  # Store handler reference for auto-flush
        self._setup_logger()
    
    def _get_ec2_region(self) -> str:
        """
        Auto-detect AWS region from EC2 instance metadata.
        
        Returns:
            str: AWS region name, defaults to 'us-east-1' if detection fails
        """
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
                        print(f"✅ Auto-detected AWS region from EC2 metadata: {region}")
                        return region
            
            # Fallback if IMDSv2 fails - try IMDSv1
            metadata_url = "http://169.254.169.254/latest/dynamic/instance-identity/document"
            metadata_response = requests.get(metadata_url, timeout=2)
            if metadata_response.status_code == 200:
                instance_data = metadata_response.json()
                region = instance_data.get('region')
                if region:
                    print(f"✅ Auto-detected AWS region from EC2 metadata (IMDSv1): {region}")
                    return region
                    
        except Exception as e:
            print(f"⚠️  Could not auto-detect region from EC2 metadata: {str(e)}")
            print(f"   Falling back to default region: us-west-2")
        
        # Default fallback
        return "us-west-2"
    
    def _setup_logger(self):
        """Setup the logger with CloudWatch and console handlers."""
        # Create or get logger
        self.logger = logging.getLogger(self.service_name)
        self.logger.setLevel(self.log_level)
        
        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Setup CloudWatch handler
        self._setup_cloudwatch_handler(formatter)
        
        # Setup console handler if enabled
        if self.console_logging:
            self._setup_console_handler(formatter)
        
        # Log initialization message
        self.logger.info(f"Logger initialized for {self.service_name} - Region: {self.region}, Log Group: {self.log_group_name}")
    
    def _setup_cloudwatch_handler(self, formatter: logging.Formatter):
        """Setup CloudWatch logging handler."""
        try:
            # Create CloudWatch client
            cloudwatch_client = boto3.client('logs', region_name=self.region)
            
            # Add CloudWatch handler
            self.cloudwatch_handler = watchtower.CloudWatchLogHandler(
                log_group_name=self.log_group_name,
                log_stream_name=self.log_stream_name,
                boto3_client=cloudwatch_client,
                create_log_group=self.create_log_group,
                use_queues=self.use_queues,
                send_interval=self.send_interval,
                max_batch_size=self.max_batch_size,
                max_batch_count=self.max_batch_count
            )
            self.cloudwatch_handler.setLevel(self.log_level)
            self.cloudwatch_handler.setFormatter(formatter)
            
            # If auto_flush is enabled, wrap the handler with a custom handler that flushes immediately
            if self.auto_flush:
                wrapped_handler = AutoFlushHandler(self.cloudwatch_handler)
                self.logger.addHandler(wrapped_handler)
            else:
                self.logger.addHandler(self.cloudwatch_handler)
            
            self.cloudwatch_enabled = True
            print(f"✅ CloudWatch logging enabled: {self.log_group_name}/{self.log_stream_name}")
            if self.auto_flush:
                print(f"   ⚡ Auto-flush enabled - logs sent immediately to CloudWatch")
            
        except Exception as e:
            self.cloudwatch_enabled = False
            print(f"⚠️  CloudWatch logging not available: {str(e)}")
            print("   Falling back to console logging only")
    
    def _setup_console_handler(self, formatter: logging.Formatter):
        """Setup console logging handler."""
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
    
    def get_logger(self) -> logging.Logger:
        """
        Get the configured logger instance.
        
        Returns:
            logging.Logger: Configured logger instance
        """
        return self.logger
    
    def is_cloudwatch_enabled(self) -> bool:
        """
        Check if CloudWatch logging is enabled.
        
        Returns:
            bool: True if CloudWatch logging is active, False otherwise
        """
        return self.cloudwatch_enabled
    
    def get_log_group_name(self) -> str:
        """
        Get the CloudWatch log group name.
        
        Returns:
            str: Log group name
        """
        return self.log_group_name
    
    def get_log_stream_name(self) -> str:
        """
        Get the CloudWatch log stream name.
        
        Returns:
            str: Log stream name
        """
        return self.log_stream_name
    
    @staticmethod
    def create_logger(
        log_group_name: str,
        service_name: str = "default-service",
        region: Optional[str] = None,
        **kwargs
    ) -> logging.Logger:
        """
        Static factory method to create and return a logger instance.
        
        This is a convenience method for quick logger creation.
        
        Args:
            log_group_name (str): CloudWatch log group name
            service_name (str): Name of the service
            region (str, optional): AWS region (None = auto-detect)
            **kwargs: Additional arguments passed to CloudWatchLogger
        
        Returns:
            logging.Logger: Configured logger instance
        """
        cw_logger = CloudWatchLogger(
            log_group_name=log_group_name,
            service_name=service_name,
            region=region,
            **kwargs
        )
        return cw_logger.get_logger()


# Example usage functions
def example_basic_usage():
    """Example of basic usage."""
    # Create logger with minimal configuration
    cw_logger = CloudWatchLogger(
        log_group_name="/aws/ec2/my-service",
        service_name="my-service"
    )
    
    logger = cw_logger.get_logger()
    logger.info("This is a test log message")


def example_custom_log_group():
    """Example with custom log group name."""
    # Create logger with custom log group
    cw_logger = CloudWatchLogger(
        log_group_name="/aws/lambda/my-custom-function",
        service_name="lambda-function"
    )
    
    logger = cw_logger.get_logger()
    logger.info("Lambda function started")


def example_factory_method():
    """Example using the factory method."""
    # Quick logger creation using factory method
    logger = CloudWatchLogger.create_logger(
        log_group_name="/aws/ec2/quick-service",
        service_name="quick-service",
        log_level=logging.DEBUG
    )
    
    logger.debug("Debug message")
    logger.info("Info message")


if __name__ == "__main__":
    # Run examples
    print("Example 1: Basic Usage")
    example_basic_usage()
    
    print("\nExample 2: Custom Log Group")
    example_custom_log_group()
    
    print("\nExample 3: Factory Method")
    example_factory_method()
