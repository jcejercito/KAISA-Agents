import os
import json
import boto3
import asyncio
import logging
from typing import Any, Dict

# Agents (from first lambda)
from agents import curriculum_agent, quizzer_agent, review_agent, general_agent

# Repositories, models, utils (from second lambda)
from repositories.chat_repository import ChatRepository
from repositories.user_session_repository import UserSessionRepository
from models.file_model import File
from utils.chat_utils import initialize_aws_clients, initialize_repository_tables

# Initialize AWS clients and repository tables (side-effects)
initialize_aws_clients()
initialize_repository_tables()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", 8))


def get_agent(agent_name: str):
    logger.info(f"Getting agent: {agent_name}")
    if agent_name == "curriculum":
        return curriculum_agent
    elif agent_name == "quizzer":
        return quizzer_agent
    elif agent_name == "reviewer":
        return review_agent
    elif agent_name == "general":
        return general_agent
    else:
        logger.error(f"Unknown agent requested: {agent_name}")
        raise ValueError(f"Unknown agent: {agent_name}")


async def stream_to_client_and_persist(
    agent_module,
    payload: Dict[str, Any],
    connection_id: str,
    domain: str,
    stage: str,
    session_id: str,
    user_id: str,
):
    """
    Stream model output chunks directly to WebSocket client AND persist final agent message
    into ChatRepository. Returns the final assembled assistant text.
    """
    logger.info(f"Starting stream for user {user_id}, session {session_id}")
    apigw = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=f"https://{domain}/{stage}"
    )

    assistant_chunks = []
    chunk_count = 0
    agent_response = ""
    
    try:
        logger.info("Beginning agent streaming")
        # Mark start to client
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({"session_id": session_id, "user_input": payload["user_input"], "agent_response": "", "type": "start_of_message"})
        )
        async for chunk in agent_module.stream_async(payload):
            chunk_text = chunk
            # chunk_count += 1
            
            # # Extract text from streaming chunks
            # chunk_text = ""
            # try:
            #     logger.info(f"Chunk data: {chunk}")
            #     # Handle the actual chunk format from the logs
            #     # if isinstance(chunk, dict) and 'data' in chunk:
            #     #     data_str = str(chunk['data'])

            #     #     # # Check if this chunk contains the final result
            #     #     # if "'result': AgentResult(" in data_str:
            #     #     #     # Extract the text content from the AgentResult
            #     #     #     import re
            #     #     #     text_match = re.search(r"'text': \"(.*?)\"(?=\}])", data_str, re.DOTALL)
            #     #     #     if text_match:
            #     #     #         # Clean up the extracted text
            #     #     #         clean_text = text_match.group(1)
            #     #     #         clean_text = clean_text.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
            #     #     #         agent_response = clean_text
            #     #     #     continue
            #     #     # else:
            #     #     # Parse contentBlockDelta format
            #     #     if 'event' in data_str and 'contentBlockDelta' in data_str:
            #     #         import ast
            #     #         try:
            #     #             chunk_dict = ast.literal_eval(data_str)
            #     #             if 'event' in chunk_dict and 'contentBlockDelta' in chunk_dict['event']:
            #     #                 delta = chunk_dict['event']['contentBlockDelta'].get('delta', {})
            #     #                 chunk_text = delta.get('text', '')
            #     #         except:
            #     #             chunk_text = ""
            #     #     else:
            #     #         chunk_text = data_str
            #     if isinstance(chunk, dict) and 'event' in chunk:
            #         if 'contentBlockDelta' in chunk['event']:
            #             delta = chunk['event']['contentBlockDelta'].get('delta', {})
            #             chunk_text = delta.get('text', '')
            #     elif hasattr(chunk, 'text'):
            #         chunk_text = chunk.text
            #     else:
            #         # Convert to string and filter out metadata chunks
            #         chunk_str = str(chunk)
            #         if any(x in chunk_str for x in ['init_event_loop', 'start_event_loop', 'messageStart', 'messageStop']):
            #             continue
            #         chunk_text = chunk_str
            # except Exception as e:
            #     logger.warning(f"Error processing chunk: {e}")
            #     continue
            
            # Send text chunks to WebSocket client
            if chunk_text and chunk_text.strip():
                # logger.info(f"chunk text: {chunk_text}")
                apigw.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps({"session_id": session_id, "user_input": payload["user_input"], "agent_response": chunk_text, "type": "in_progress"})
                )
                # chunk_text = json.loads(chunk_text)
                # text_chunk = chunk_text['event']['contentBlockDelta']['delta']['text']
                assistant_chunks.append(chunk_text)

        logger.info(f"Streaming completed. Total chunks: {chunk_count}")
        
        # Mark completion to client
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({"session_id": session_id, "user_input": payload["user_input"], "agent_response": "", "type": "end_of_message"})
        )

        # Use parsed agent_response or fallback to concatenated chunks
        if not agent_response:
            agent_response = "".join(assistant_chunks)
        
        logger.info(f"Agent response length: {len(agent_response)} characters")

        # Persist agent message
        logger.info(f"Persisting agent response to database. Response: {agent_response}")
        chat_object_agent = ChatRepository.initialize_chat_agent(
            user_id=user_id,
            agent_response=agent_response,
            session_id=session_id
        )
        ChatRepository.save(chat_object=chat_object_agent)
        logger.info("Agent response saved successfully")

        return agent_response

    except Exception as stream_exc:
        logger.exception(f"Error during streaming: {str(stream_exc)}")
        # Attempt to notify client of streaming error
        try:
            apigw.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps({"type": "error", "error": str(stream_exc)})
            )
        except Exception:
            logger.exception("Failed to post streaming error to client")

        raise


async def async_handler(event, context):
    """
    Async entrypoint: handles WebSocket event, session handling, saves user message,
    compiles context and streams agent output to client while persisting it.
    """
    logger.info(f"Lambda invoked with event keys: {list(event.keys())}")
    logger.info(f"Request context: {event.get('requestContext', {})}")
    
    try:
        body = json.loads(event.get("body", "{}"))
        logger.info(f"Parsed body keys: {list(body.keys())}")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request body: {e}")
        logger.error(f"Raw body: {event.get('body', 'None')}")
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON format"})}
    
    domain = event["requestContext"].get("domainName")
    stage = event["requestContext"].get("stage")
    connection_id = event["requestContext"].get("connectionId")
    
    logger.info(f"WebSocket context - domain: {domain}, stage: {stage}, connection_id: {connection_id}")

    if not connection_id or not domain or not stage:
        logger.error("Missing WebSocket requestContext fields")
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid WebSocket event"})}

    agent_name = body.get("agent", "general")
    user_id = body.get("user_id")
    user_input = body.get("user_input")
    session_id = body.get("session_id")
    file_input = None
    
    logger.info(f"Request params - agent: {agent_name}, user_id: {user_id}, session_id: {session_id}")
    logger.info(f"User input length: {len(user_input) if user_input else 0}")

    if not user_id or not user_input:
        logger.error(f"Missing required fields - user_id: {bool(user_id)}, user_input: {bool(user_input)}")
        ChatRepository.push_to_client(
            connection_id=connection_id,
            response={"error": "Missing user_id or user_input", "connectionId": connection_id}
        )
        return {"statusCode": 400, "body": json.dumps({"error": "Missing user_id or user_input"})}

    # Send initial processing acknowledgment
    logger.info("Sending processing acknowledgment to client")
    ChatRepository.push_to_client(
        connection_id=connection_id,
        response={"message": "processing", "connectionId": connection_id}
    )

    # Handle file input if present
    if body.get("file_input"):
        logger.info("Processing file input")
        file_data = body["file_input"]
        file_input = File(
            file_name=file_data.get("file_name"),
            file_type=file_data.get("file_type"),
            s3_file_name=file_data.get("s3_file_name"),
            file_size=file_data.get("file_size")
        )
        logger.info(f"File input created: {file_data.get('file_name')}")

    # Session handling
    logger.info("Starting session handling")
    try:
        if session_id:
            logger.info(f"Looking up existing session: {session_id}")
            user_session = UserSessionRepository.get_user_session(user_id=user_id, session_id=session_id)
            if not user_session:
                logger.error(f"Session not found: {session_id}")
                ChatRepository.push_to_client(
                    connection_id=connection_id,
                    response={"error": "Session not found", "connectionId": connection_id}
                )
                return {"statusCode": 404, "body": json.dumps({"error": "Session not found"})}
            logger.info(f"Found existing session with {user_session.message_count} messages")
        else:
            logger.info("Creating new session")
            session_id = UserSessionRepository.construct_session_id(user_id=user_id)
            user_session = UserSessionRepository.initialize_user_session(
                user_id=user_id, title="New Chat", session_id=session_id, summary=""
            )
            UserSessionRepository.save(session_object=user_session)
            logger.info(f"New session created: {session_id}")
    except Exception as sess_exc:
        logger.exception(f"Error handling user session: {str(sess_exc)}")
        ChatRepository.push_to_client(
            connection_id=connection_id,
            response={"error": str(sess_exc), "connectionId": connection_id}
        )
        return {"statusCode": 500, "body": json.dumps({"error": str(sess_exc)})}

    # Save user message
    logger.info("Saving user message")
    try:
        chat_object_user = ChatRepository.initialize_chat_user(
            user_input=user_input,
            session_id=session_id,
            user_id=user_id,
            file_input=file_input
        )
        ChatRepository.save(chat_object=chat_object_user)
        logger.info("User message saved successfully")

        user_session.message_count = (user_session.message_count or 0) + 1
        UserSessionRepository.save(session_object=user_session)
        logger.info(f"Updated session message count to: {user_session.message_count}")
    except Exception as save_exc:
        logger.exception(f"Error saving user chat: {str(save_exc)}")
        ChatRepository.push_to_client(
            connection_id=connection_id,
            response={"error": str(save_exc), "connectionId": connection_id}
        )
        return {"statusCode": 500, "body": json.dumps({"error": str(save_exc)})}

    # Compile chat history
    logger.info("Compiling chat history")
    try:
        if body.get("session_id"):
            logger.info(f"Compiling history for existing session with context window: {CONTEXT_WINDOW}")
            recent_messages = ChatRepository.compile_chat_history(
                session_id=session_id,
                message_count=user_session.message_count,
                context_window=CONTEXT_WINDOW
            )
            summary = ChatRepository.format_session_summary(current_summary=user_session.session_summary)
            chat_messages = summary + recent_messages
            logger.info(f"Compiled {len(recent_messages)} recent messages with summary")
        else:
            logger.info("Compiling history for new session")
            chat_messages = ChatRepository.compile_chat_history(
                session_id=session_id,
                message_count=user_session.message_count,
                context_window=CONTEXT_WINDOW
            )
            logger.info(f"Compiled {len(chat_messages)} messages for new session")
    except Exception as compile_exc:
        logger.exception(f"Error compiling chat history: {str(compile_exc)}")
        ChatRepository.push_to_client(
            connection_id=connection_id,
            response={"error": str(compile_exc), "connectionId": connection_id}
        )
        return {"statusCode": 500, "body": json.dumps({"error": str(compile_exc)})}

    # Send chat context to client
    logger.info("Sending chat context to client")
    ChatRepository.push_to_client(
        connection_id=connection_id,
        response={
            "session_id": session_id,
            "user_id": user_id,
            "chat_messages": chat_messages,
            "has_file_attachment": file_input is not None,
            "connectionId": connection_id
        }
    )

    # Prepare payload for agent: full chat context + latest user input
    logger.info("Preparing agent payload")
    agent_payload = {
        "chat_messages": chat_messages,
        "user_input": user_input,
        "user_id": user_id,
        "session_id": session_id,
        "file_input": file_input,
        **{k: v for k, v in body.get("payload", {}).items()}
    }
    logger.info(f"Agent payload prepared with {len(chat_messages)} messages")

    # Forward to agent and stream results
    logger.info(f"Getting agent module: {agent_name}")
    try:
        agent_module = get_agent(agent_name)
        logger.info(f"Agent module retrieved successfully: {agent_module}")
    except ValueError as e:
        logger.error(f"Invalid agent name: {agent_name}")
        ChatRepository.push_to_client(
            connection_id=connection_id,
            response={"error": str(e), "connectionId": connection_id}
        )
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}

    try:
        logger.info("Starting agent streaming process")
        await stream_to_client_and_persist(
            agent_module=agent_module,
            payload=agent_payload,
            connection_id=connection_id,
            domain=domain,
            stage=stage,
            session_id=session_id,
            user_id=user_id
        )
        logger.info("Lambda execution completed successfully")
        return {"statusCode": 200, "body": json.dumps({"message": "OK"})}
    except Exception as e:
        logger.exception(f"Error while streaming from agent: {str(e)}")
        ChatRepository.push_to_client(
            connection_id=connection_id,
            response={"error": str(e), "connectionId": connection_id}
        )
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def lambda_handler(event, context):
    """Lambda synchronous entrypoint."""
    logger.info("Lambda handler started")
    try:
        result = asyncio.run(async_handler(event, context))
        logger.info(f"Lambda handler completed with status: {result.get('statusCode')}")
        return result
    except Exception as e:
        logger.exception(f"Fatal error in lambda handler: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
