import boto3, os
from boto3.dynamodb.conditions import Key

BEDROCK_REGION = os.getenv("BEDROCK_REGION")
AWS_ACCESS_KEY_ID = os.getenv("ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = os.getenv("SECRET_KEY")

def get_chat_context(session_id, limit=10):
    dynamodb = boto3.resource("dynamodb",
        region_name=BEDROCK_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    table = dynamodb.Table(os.getenv("CHAT_TABLE"))
    
    response = table.query(
        KeyConditionExpression=Key('PK').eq(session_id),
        ScanIndexForward=False,
        Limit=limit
    )
    
    context = ""
    for item in reversed(response['Items']):
        if(item['role'] == "user"):
            context += f"User: {item['message']}\n"
        else:
            context += f"Assistant: {item['message']}\n"
    
    return context

def build_message_with_context(session_id, current_message):
    chat_history = get_chat_context(session_id)
    
    if chat_history:
        return f"Previous conversation:\n{chat_history}Current message: {current_message}"
    else:
        return current_message
