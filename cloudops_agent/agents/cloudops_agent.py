import boto3
import os
from dotenv import load_dotenv
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from botocore.exceptions import BotoCoreError, NoCredentialsError, EndpointConnectionError
from pydantic import BaseModel

load_dotenv()

class InstanceInput(BaseModel):
    instance_id: str

class EC2InstanceDetailInput(BaseModel):
    instance_id: str

@tool
def list_ec2_instances():
    """List all EC2 instances."""
    print("list ec2")
    try:
        session = boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )

        ec2 = session.client("ec2")
        response = ec2.describe_instances()
        instances = []
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                instances.append({
                    "InstanceId": instance["InstanceId"],
                    "State": instance["State"]["Name"],
                    "Type": instance["InstanceType"]
                })
        return instances
    except Exception as e:
        print("Failed to connect to aws:")
        return f"AWS error: {str(e)}"

@tool
def list_s3_buckets():
    """List all S3 buckets."""
    print("list s3")
    try:
        session = boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        s3 = session.client("s3")
        response = s3.list_buckets()
        return [bucket["Name"] for bucket in response["Buckets"]]
    except Exception as e:
        print("Failed to connect to aws:")
        return f"AWS error: {str(e)}"

@tool("restart_ec2_instance",args_schema=InstanceInput)
def restart_instance(instance_id: str):
    """Restart a specific EC2 instance."""
    print(f"restart ec2 {instance_id}")
    try:
        session = boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )

        ec2 = session.client("ec2")
        s3 = session.client("s3")
        ec2.reboot_instances(InstanceIds=[instance_id])
        return f"Instance {instance_id} is rebooting."
    except Exception as e:
        print("Failed to connect to aws:")
        return f"AWS error: {str(e)}"

@tool("get_ec2_instance_details",args_schema=EC2InstanceDetailInput)
def get_ec2_instance_details(instance_id: str):
    """Get details of an EC2 instance. Use this when the user asks about status or details of an EC2 instance — even if they don’t re-type the instance ID, reuse recent context."""
    print(f"Fetching details for instance {instance_id}")
    try:
        session = boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        ec2 = session.client("ec2")
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        instance = response["Reservations"][0]["Instances"][0]

        details = {
            "InstanceId": instance.get("InstanceId"),
            "State": instance.get("State", {}).get("Name"),
            "Type": instance.get("InstanceType"),
            "Public IP": instance.get("PublicIpAddress"),
            "Private IP": instance.get("PrivateIpAddress"),
            "LaunchTime": str(instance.get("LaunchTime")),
            "AvailabilityZone": instance.get("Placement", {}).get("AvailabilityZone"),
            "Tags": instance.get("Tags", [])
        }

        return details
    except Exception as e:
        return f"AWS error: {str(e)}"


def create_cloudops_agent():
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0")
    tools = [list_ec2_instances, list_s3_buckets, restart_instance, get_ec2_instance_details]
    return create_react_agent(model=llm, tools=tools, prompt=("You are a helpful AWS CloudOps assistant.\n"
        "You can list EC2/S3, reboot instances, and get instance details.\n"
        "Always try to use previous context in the conversation — for example, if the user mentions an EC2 instance earlier, and then says 'get the details', assume they're referring to the same instance.\n"
        "If something is unclear, ask questions.\n"
        "Never ask for information the user has already provided unless absolutely necessary."
    ))
