import logging
import boto3
import os
import requests
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError

# Configure logging
logger = logging.getLogger(__name__)

class SecretValidator:
    """
    Class to validate secrets by fetching them from AWS SSM Parameter Store.
    """
    
    def __init__(self):
        self.ssm_client = None
        self.cached_secret = None
        # Allow secret path to be configurable via environment variable
        self.secret_parameter_path = os.getenv('SECRET_PARAMETER_PATH', '/H9VV/CCS/SlackApp/ws/secret')
        # Auto-detect region using the same method as CloudWatch logger
        self.region = self._get_ec2_region()
        logger.info(f"SecretValidator initialized - Region: {self.region}, Secret Path: {self.secret_parameter_path}")
    
    def _get_ec2_region(self) -> str:
        """
        Auto-detect AWS region from EC2 instance metadata.
        Uses the same method as CloudWatch logger for consistency.
        
        Returns:
            str: AWS region name, defaults to 'us-west-2' if detection fails
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
        
        # Default fallback to us-west-2
        return "us-west-2"
    
    def create_boto3_client(self):
        """
        Creates a boto3 client for the SSM service.
        Uses auto-detected region from EC2 metadata.

        Returns:
            boto3.client : A boto3 SSM client object
        """
        try:
            logger.info(f"Region is: {self.region}")
            
            logger.info("Creating boto3 client for SSM")
            ssm_client = boto3.client('ssm', self.region)
            logger.info(f"SSM client created successfully")
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
    
    def fetch_secret_from_aws(self):
        """
        Fetch the secret from AWS SSM Parameter Store.
        
        Returns:
            str: The secret value from AWS SSM
        """
        try:
            if not self.ssm_client:
                self.ssm_client = self.create_boto3_client()
            
            logger.info(f"SSM client is: {self.ssm_client}")
            
            # Print proxy environment variables for debugging
            http_proxy = os.getenv('http_proxy') or os.getenv('HTTP_PROXY')
            https_proxy = os.getenv('https_proxy') or os.getenv('HTTPS_PROXY')
            no_proxy = os.getenv('no_proxy') or os.getenv('NO_PROXY')
            
            logger.debug(f"http_proxy: {http_proxy}")
            logger.debug(f"https_proxy: {https_proxy}")
            logger.debug(f"no_proxy: {no_proxy}")
            
            response = self.ssm_client.get_parameters(
                Names=[
                    self.secret_parameter_path
                ],
                WithDecryption=True
            )
            logger.info(f"SSM response received for parameter: {self.secret_parameter_path}")
            
            # Extract the secret value
            parameters = response.get('Parameters', [])
            for param in parameters:
                if param['Name'] == self.secret_parameter_path:
                    logger.info(f"Secret found for parameter: {self.secret_parameter_path}")
                    secret_value = param['Value']
                    self.cached_secret = secret_value  # Cache for future use
                    return secret_value
            
            # If parameter not found
            logger.error(f"Parameter {self.secret_parameter_path} not found in SSM")
            raise ValueError(f"Parameter {self.secret_parameter_path} not found in SSM")
            
        except (BotoCoreError, ClientError) as e:
            logger.error(f"Failed to retrieve parameter {self.secret_parameter_path} from SSM: {e}")
            raise
        except ValueError as e:
            logger.error(f"Value error: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching secret: {e}")
            raise
    
    def validate_secret(self, provided_secret):
        """
        Validate the provided secret against the AWS stored secret.
        
        Args:
            provided_secret (str): The secret to validate
            
        Returns:
            bool: True if the secret is valid, False otherwise
        """
        try:
            if not provided_secret:
                logger.warning("No secret provided for validation")
                return False
            
            # Fetch the secret from AWS if not cached
            if not self.cached_secret:
                aws_secret = self.fetch_secret_from_aws()
            else:
                aws_secret = self.cached_secret
            
            # Compare the provided secret with the AWS secret
            is_valid = provided_secret == aws_secret
            
            if is_valid:
                logger.info("Secret validation successful")
            else:
                logger.warning("Secret validation failed - provided secret does not match AWS secret")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error during secret validation: {e}")
            return False
    
    def refresh_secret_cache(self):
        """
        Refresh the cached secret by fetching it again from AWS.
        This can be called periodically or when secret validation fails.
        """
        try:
            logger.info("Refreshing secret cache from AWS")
            self.cached_secret = None
            self.fetch_secret_from_aws()
            logger.info("Secret cache refreshed successfully")
        except Exception as e:
            logger.error(f"Failed to refresh secret cache: {e}")
            raise


# Global secret validator instance
secret_validator = SecretValidator()