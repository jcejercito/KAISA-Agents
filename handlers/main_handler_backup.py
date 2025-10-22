import os
import json
import boto3
import asyncio
from agents import curriculum_agent, quizzer_agent, review_agent, general_agent

BEDROCK_REGION = os.getenv("BEDROCK_REGION")
AWS_ACCESS_KEY_ID = os.getenv("ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = os.getenv("SECRET_KEY")

dynamodb = boto3.resource("dynamodb",
    region_name=BEDROCK_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

CHAT_TABLE = os.getenv("CHAT_TABLE")

def get_agent(agent_name):
    if agent_name == "curriculum":
        return curriculum_agent
    elif agent_name == "quizzer":
        return quizzer_agent
    elif agent_name == "reviewer":
        return review_agent
    elif agent_name == "general":
        return general_agent
    else:
        raise ValueError(f"Unknown agent: {agent_name}")

async def stream_to_client(agent_module, payload, connection_id, domain, stage):
    """Stream model output chunks directly to WebSocket client."""
    apigw = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=f"https://{domain}/{stage}"
    )

    async for chunk in agent_module.stream_async(payload):
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({"type": "chunk", "data": chunk})
        )

    # Mark completion
    apigw.post_to_connection(
        ConnectionId=connection_id,
        Data=json.dumps({"type": "done"})
    )

async def async_handler(event, context):
    """Async entrypoint for WebSocket route (true streaming)."""
    body = json.loads(event.get("body", "{}"))
    agent_name = body.get("agent")
    payload = body.get("payload", {})

    connection_id = event["requestContext"]["connectionId"]
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]

    try:
        agent_module = get_agent(agent_name)
        await stream_to_client(agent_module, payload, connection_id, domain, stage)
        return {"statusCode": 200}

    except Exception as e:
        boto3.client("apigatewaymanagementapi",
            endpoint_url=f"https://{domain}/{stage}"
        ).post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({"error": str(e)})
        )
        return {"statusCode": 500}

def lambda_handler(event, context):
    """Lambda handler entrypoint."""
    return asyncio.run(async_handler(event, context))
