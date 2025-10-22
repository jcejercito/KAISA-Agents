import os
import boto3
from botocore.config import Config

from repositories.chat_repository import ChatRepository
from repositories.user_session_repository import UserSessionRepository

def initialize_aws_clients(region=None):
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    config = Config(
        connect_timeout=int(os.getenv("BEDROCK_CONNECT_TIMEOUT", 5)),
        read_timeout=int(os.getenv("BEDROCK_READ_TIMEOUT", 120)),
        retries={"max_attempts": int(os.getenv("BEDROCK_MAX_ATTEMPTS", 2)), "mode": "standard"},
    )
    
    ChatRepository.DDB_CLIENT = boto3.client("dynamodb", region_name=region)
    UserSessionRepository.DDB_CLIENT = boto3.client("dynamodb", region_name=region)
    
    # WebSocket client for real-time communication
    api_id = os.getenv("WEBSOCKET_API_ID")
    stage = os.getenv("WEBSOCKET_STAGE", "prod")
    if api_id:
        ChatRepository.WEBSOCKET_CLIENT = boto3.client(
            'apigatewaymanagementapi',
            endpoint_url=f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        )

def initialize_repository_tables():
    ChatRepository.DDB_TABLE_NAME = os.getenv("CHAT_TABLE", None)
    UserSessionRepository.DDB_TABLE_NAME = os.getenv("CHAT_TABLE", None)
