from http import cookies as cookie
import jwt
import base64
import os 
import boto3
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.backends import default_backend
import traceback

class JwtUtil(object):
    '''
    Class to support JWT utility functions.

    Attributes
    ----------
        event: ALBEvent
            A dictionary-like object of Lambda event data.

        keys : dict
            A dictionary of base64 encoded public keys used to validate SSO JWTs for different environments.

    Methods
    -------
        verify_jwt_token(token, env):
            Verify JWT token and return decoded payload or None if invalid.
    '''
    def __init__(self, event):
        self.event = event

        # Public keys to validate SSO JWT token signature
        self.keys = {
            'PROD': 'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSURhakNDQWxJQ0NRQ1JxZ1JvWDJCdjNEQU5CZ2txaGtpRzl3MEJBUXNGQURCN01Rc3dDUVlEVlFRR0V3SlYKVXpFTE1Ba0dBMVVFQ0F3Q1ZGZ3hEekFOQmdOVkJBY01Ca2xTVmtsT1J6RVFNQTRHQTFVRUNnd0hWa1ZTU1ZwUApUakVQTUEwR0ExVUVDd3dHVDA1RlUxTlBNU3N3S1FZRFZRUUREQ0pXWlhKcGVtOXVJRTlPUlZOVFR5QlFVazlFCklFTkJJRU5sY25ScFptbGpZWFJsTUI0WERURTNNRFl4TXpFMk1qYzBOVm9YRFRNM01EWXdPREUyTWpjME5Wb3cKY3pFTE1Ba0dBMVVFQmhNQ1ZWTXhDekFKQmdOVkJBZ01BbFJZTVE4d0RRWURWUVFIREFaSlVsWkpUa2N4RURBTwpCZ05WQkFvTUIxWkZVa2xhVDA0eER6QU5CZ05WQkFzTUJrOU9SVk5UVHpFak1DRUdBMVVFQXd3YVZsb2dUMDVGClUxTlBJRkJTVDBRZ1EyVnlkR2xtYVdOaGRHVXdnZ0VpTUEwR0NTcUdTSWIzRFFFQkFRVUFBNElCRHdBd2dnRUsKQW9JQkFRRGR5d3RDcTlYa1IxbTc1UE0vSVZOdURVaVUrd0dMcFFQNkR3SjV6d2NzZnRJV0h6Wkl6aVR6OXFHRQpWdGdQN3AwUjYyenFtTDFYVDNFVGpsTjlBVlp4cmN4c2NGM1RwL0lBQ0ZLejIvSG95WS9EY3RPeTVtMFJkVktXCkl5TVlFVTU3Tng4UTRiN2RrVEtjZFA0eHZVeFl0dDV2ZG1RMldxc3hySXFabzlJTlpvS2YyOStVNW53MUZHdzYKSGNNYjRPNUM4Zk4vOUlqSFpTSDl6Q0VEMHVWb3BRaDdKdEV3SGN1dFpGMXVLbFNuZUgyL0NqUWtPNVF0a3A3UQp5L21QMTBxZFpBY1JjYjROelNhUXJ5VHI4SVJvcU13UWN6OUlCNTZrcHBrV2JPV3Fib2pWek5NakU1cVhQNmI3CnNsa2cwNkhPaTRyOHM3eWJodDJ5b29yUytxWkJBZ01CQUFFd0RRWUpLb1pJaHZjTkFRRUxCUUFEZ2dFQkFGMHQKc09sZ1JGa1JjVktjUWFpaWp5NHZPQU9CVi9wdEQ5aCtwTCtEUXpyUGt1d0gvc21CQUZWMDA2cEJUQWZOdTBrawp6WGtzYXVrbExwaFkvUnMyYUoxbmZuVm5xTFVlb21oTXU3TjJBK0tPRkdralpSQlRITWRLZ25xSU1GUUo4M2VMCmErT0FHOWZJY0VWemJNS1lvTEM4YXdGekdGenNzUUdDMitaZloxWkt5NDREWXJGaHNQVW14RUU3NlpEaU9OTkoKaGR3KzFKRVd2Mkg0Mkp2c3MwNXEwYm9YSFhNMjM1eHZjTzJGYzBESnFSMFYvcjZIcUh3dVpsOW5VMGovdXFxZgpkY3RTM1RGaG1VbGRoQ1BiQzd6VFNyTC9zbXV6STRMTXRpQ29XS3R1OGVDQTZITzBNN2RFRnVibWc4V0xlaG92CnJWZzlVWGNEbkI1MFFrMGpQWEU9Ci0tLS0tRU5EIENFUlRJRklDQVRFLS0tLS0KCg',
            'NONPROD': 'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSURhRENDQWxBQ0NRRG1KMTZJL1dscHFEQU5CZ2txaGtpRzl3MEJBUXNGQURCNk1Rc3dDUVlEVlFRR0V3SlYKVXpFTE1Ba0dBMVVFQ0F3Q1ZGZ3hEekFOQmdOVkJBY01Ca2xTVmtsT1J6RVFNQTRHQTFVRUNnd0hWa1ZTU1ZwUApUakVQTUEwR0ExVUVDd3dHVDA1RlUxTlBNU293S0FZRFZRUUREQ0ZXWlhKcGVtOXVJRTlPUlZOVFR5QlZRVlFnClEwRWdRMlZ5ZEdsbWFXTmhkR1V3SGhjTk1UY3dOakU0TURJMU16QTJXaGNOTXpjd05qRXpNREkxTXpBMldqQnkKTVFzd0NRWURWUVFHRXdKVlV6RUxNQWtHQTFVRUNBd0NWRmd4RHpBTkJnTlZCQWNNQmtsU1ZrbE9SekVRTUE0RwpBMVVFQ2d3SFZrVlNTVnBQVGpFUE1BMEdBMVVFQ3d3R1QwNUZVMU5QTVNJd0lBWURWUVFEREJsV1dpQlBUa1ZUClUwOGdWVUZVSUVObGNuUnBabWxqWVhSbE1JSUJJakFOQmdrcWhraUc5dzBCQVFFRkFBT0NBUThBTUlJQkNnS0MKQVFFQThybldQZTZEeWx6bk8yMnZWV2taVk8yOFoySWRGU1RPdnN0ejNlbUQ5QkFEMVZVZklnVlRnc2N5b1dwSApIQXpWS0dqTG94YnBWVUpFYkEwZE95cEpjcEQzbVcrSW5PMmZ3Z2l1WXlyUkRhZEN5aE14TUpHTlJDa3VsNTM3CkFaQjhOeDVwSEdEcVI0WFFkU2RiUUxFNFFYb1liZmM1c2hsK1hIU21nYW1hR1lmZjNDSlgzeDRTdjRHTGNlbTgKc0NvblZpdXNOTXpSbDM3OTFpdjBuODdYOFp4SVFKOVdRY25Td00vdmJQYStRd01TOWRLZmszZ3pkMXJxNDc5TgpCLzhIQjNlOUNzdnI5YXJyL1F1d3hiZVV6bGpLV2JPMXBxTENYS2N3Y1NoZ2l3TjQ3bnBhN2FjNGowODhXWmk2Ci80Z2Q3WGdWdDFOWFpNeE9lWWlOQkoyajFRSURBUUFCTUEwR0NTcUdTSWIzRFFFQkN3VUFBNElCQVFBRzhwRFIKVSszK2RSMlBSTloxVkphazNjT01ZRmpWRHRuaWlxbi9aU0hjNFZvSkVLQTZ1V0JUZEJhMWprenFWYlJYVHZtZAp6WnJIRUcyWVNJY3FpbnNOUWVwSGZlS0U1YkNycy84WmdiTW04NEZzaU4rZklpZ2trNFlockNUb2RLaWFQcS9uCjRZTmM5MHBKMUwxdHVVbFhSeU9ISERYalBiTHQzQmVXb0ZEQldDVXNZSXFpaFIwc1Q0Qy8xQ3k2aCtpTlJGQnEKR3R0eGZpYWdjSDk4eU53azA4ZVNlQS8xc29Ibi9yeERoYUsyTEZxRUc0TjZYME5WeVBRV0NkaHRNNWwxV2VhdQp0L08vL0NUSVN5SUlKcUV4TmVQTUk1Y3c0aVZDWi9OU2o1cXpHNXNndkZZTEptLzdpOHVab3doZDZ4SG9FLzVLCklSbkprTXJGdjNGZUR6VkYKLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo',
            'DEV': 'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSURhRENDQWxBQ0NRRG1KMTZJL1dscHFEQU5CZ2txaGtpRzl3MEJBUXNGQURCNk1Rc3dDUVlEVlFRR0V3SlYKVXpFTE1Ba0dBMVVFQ0F3Q1ZGZ3hEekFOQmdOVkJBY01Ca2xTVmtsT1J6RVFNQTRHQTFVRUNnd0hWa1ZTU1ZwUApUakVQTUEwR0ExVUVDd3dHVDA1RlUxTlBNU293S0FZRFZRUUREQ0ZXWlhKcGVtOXVJRTlPUlZOVFR5QlZRVlFnClEwRWdRMlZ5ZEdsbWFXTmhkR1V3SGhjTk1UY3dOakU0TURJMU16QTJXaGNOTXpjd05qRXpNREkxTXpBMldqQnkKTVFzd0NRWURWUVFHRXdKVlV6RUxNQWtHQTFVRUNBd0NWRmd4RHpBTkJnTlZCQWNNQmtsU1ZrbE9SekVRTUE0RwpBMVVFQ2d3SFZrVlNTVnBQVGpFUE1BMEdBMVVFQ3d3R1QwNUZVMU5QTVNJd0lBWURWUVFEREJsV1dpQlBUa1ZUClUwOGdWVUZVSUVObGNuUnBabWxqWVhSbE1JSUJJakFOQmdrcWhraUc5dzBCQVFFRkFBT0NBUThBTUlJQkNnS0MKQVFFQThybldQZTZEeWx6bk8yMnZWV2taVk8yOFoySWRGU1RPdnN0ejNlbUQ5QkFEMVZVZklnVlRnc2N5b1dwSApIQXpWS0dqTG94YnBWVUpFYkEwZE95cEpjcEQzbVcrSW5PMmZ3Z2l1WXlyUkRhZEN5aE14TUpHTlJDa3VsNTM3CkFaQjhOeDVwSEdEcVI0WFFkU2RiUUxFNFFYb1liZmM1c2hsK1hIU21nYW1hR1lmZjNDSlgzeDRTdjRHTGNlbTgKc0NvblZpdXNOTXpSbDM3OTFpdjBuODdYOFp4SVFKOVdRY25Td00vdmJQYStRd01TOWRLZmszZ3pkMXJxNDc5TgpCLzhIQjNlOUNzdnI5YXJyL1F1d3hiZVV6bGpLV2JPMXBxTENYS2N3Y1NoZ2l3TjQ3bnBhN2FjNGowODhXWmk2Ci80Z2Q3WGdWdDFOWFpNeE9lWWlOQkoyajFRSURBUUFCTUEwR0NTcUdTSWIzRFFFQkN3VUFBNElCQVFBRzhwRFIKVSszK2RSMlBSTloxVkphazNjT01ZRmpWRHRuaWlxbi9aU0hjNFZvSkVLQTZ1V0JUZEJhMWprenFWYlJYVHZtZAp6WnJIRUcyWVNJY3FpbnNOUWVwSGZlS0U1YkNycy84WmdiTW04NEZzaU4rZklpZ2trNFlockNUb2RLaWFQcS9uCjRZTmM5MHBKMUwxdHVVbFhSeU9ISERYalBiTHQzQmVXb0ZEQldDVXNZSXFpaFIwc1Q0Qy8xQ3k2aCtpTlJGQnEKR3R0eGZpYWdjSDk4eU53azA4ZVNlQS8xc29Ibi9yeERoYUsyTEZxRUc0TjZYME5WeVBRV0NkaHRNNWwxV2VhdQp0L08vL0NUSVN5SUlKcUV4TmVQTUk1Y3c0aVZDWi9OU2o1cXpHNXNndkZZTEptLzdpOHVab3doZDZ4SG9FLzVLCklSbkprTXJGdjNGZUR6VkYKLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo',
            'LOCAL': 'c2VjcmV0'
        }
    
    def verify_jwt_token(self, token, env=None):
        '''
        Verify JWT token directly without using cookies.
        
        Parameters
        ----------
            token : str
                The JWT token string to verify.
            env : str, optional
                Environment to use for key selection (PROD, NONPROD, DEV, LOCAL).
                If not provided, uses APP_ENV environment variable.
        
        Returns
        -------
            dict or None
                Decoded JWT payload if valid, None if invalid.
        '''
        if not token:
            print("Empty token provided")
            return None
        
        try:
            # Decode without verification to get header and payload
            header = jwt.get_unverified_header(token)
            decoded_jwt = jwt.decode(token, options={"verify_signature": False})
            
            # Determine environment
            if env:
                app_env = env.upper()
            else:
                app_env = os.environ.get('APP_ENV', 'DEV')
            
            print(f"Using environment: {app_env}")
            
            #app_env = 'PROD' # to do will remove it once finalize the env is prod from the prod logs
            # Get the appropriate key based on environment
            if app_env == 'PROD':
                key = self.keys['PROD']
            elif app_env == 'NONPROD':
                key = self.keys['NONPROD']
            elif app_env == 'DEV':
                key = self.keys['DEV']
            elif app_env == 'LOCAL':
                key = self.keys['LOCAL']
            else:
                # Default to PROD for unknown environments
                key = self.keys['PROD']
            
            # Use RS256 certificate-based verification (for PROD/NONPROD/DEV)
            # Handle base64 padding based on environment
            if app_env == 'PROD':
                # PROD: Properly handle base64 padding
                key_with_padding = key
                # Add padding if needed (base64 strings must be divisible by 4)
                missing_padding = len(key) % 4
                if missing_padding:
                    key_with_padding += '=' * (4 - missing_padding)
                byteArrayKey = bytearray(base64.b64decode(key_with_padding))
            else:
                # NONPROD/DEV: Use original padding method
                byteArrayKey = bytearray(base64.b64decode(key + "="))
            
            certKey = byteArrayKey.decode().encode('utf-8')
            cert_obj = load_pem_x509_certificate(certKey, default_backend())
            public_key = cert_obj.public_key()
            
            # Verify and decode the token
            decoded_token = jwt.decode(token, public_key, audience=decoded_jwt.get('aud'), algorithms=["RS256"])
            return decoded_token
            
        except Exception as e:
            print(e)
            traceback.print_exc()
            return None


# Compatibility wrapper class for WebSocket service
class AuthenticatorWrapper:
    """
    Wrapper class to provide compatibility with the existing ccs_onecloud_websocket.py
    that expects an authenticator object with verify_jwt_token and extract_token_from_header methods.
    """
    
    def __init__(self):
        # Create a mock event for JwtUtil initialization
        self.mock_event = {'headers': {}}
        self.jwt_util = JwtUtil(self.mock_event)
    
    def verify_jwt_token(self, token, env=None):
        """Verify JWT token - delegates to JwtUtil.verify_jwt_token"""
        return self.jwt_util.verify_jwt_token(token, env)
    
    def extract_token_from_header(self, authorization_header):
        """Extract JWT token from Authorization header"""
        if not authorization_header:
            return None
        
        # Handle "Bearer <token>" format
        parts = authorization_header.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            return parts[1]
        
        # If not Bearer format, assume the entire header is the token
        return authorization_header


# Global authenticator instance for backward compatibility
authenticator = AuthenticatorWrapper()
