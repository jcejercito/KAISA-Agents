import json
import boto3
import os
from typing import Optional
from strands import Agent, tool
from strands.models import BedrockModel
import sys
sys.path.append('..')
from chat_context import build_message_with_context
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Environment variables
BEDROCK_REGION = os.getenv("BEDROCK_REGION")
AWS_ACCESS_KEY_ID = os.getenv("ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = os.getenv("SECRET_KEY")
KNOWLEDGE_BASE_ID = os.getenv("KB_ID")

CONFIG_PATH = "agents/config/curriculum_config.json"
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

# -----------------------------
# TOOL: Retrieve from KB
# -----------------------------
@tool
def retrieve_from_kb(query: str, max_results: Optional[int] = 3) -> str:
    """
    Retrieves data from Amazon Bedrock knowledge base.

    Args:
        query (str): The search query or question.
        max_results (int, optional): Maximum number of results to return. Defaults to 3.

    Returns:
        str: Retrieved knowledge base results.
    """
    try:
        client = boto3.client(
            'bedrock-agent-runtime',
            region_name=BEDROCK_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )

        response = client.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': query},
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': max_results
                }
            }
        )

        results = []
        for result in response.get('retrievalResults', []):
            content = result['content'].get('text', '')
            score = result.get('score', 0)
            results.append({
                "score": round(score, 3),
                "content": content
            })

        if not results:
            return json.dumps({
                "status": "success",
                "results": [],
                "message": "No results found."
            })

        return json.dumps({
            "status": "success",
            "results": results
        })

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Error retrieving from knowledge base: {str(e)}"
        })

# -----------------------------
# TOOL: Log queries (stub)
# -----------------------------
@tool
def log_queries():
    """Placeholder for DynamoDB query logging tool."""
    return json.dumps({"status": "success", "message": "Query logged."})

async def stream_async(payload):
    """Async generator that yields streamed model output."""
    user_prompt = payload.get("user_input", payload.get("message", ""))
    file_input = payload.get("file_input", None)
    session_id = payload.get("session_id")
    user_prompt = build_message_with_context(session_id, user_prompt)
    
    # If file is uploaded, include file info in prompt
    if file_input and file_input.file_name:
        user_prompt = f"[Document attached: {file_input.file_name}]\n\n{user_prompt}"
    # Create an agent
    agent = create_agent()

    buffer = ""
    inside_thinking = False

    async for chunk in agent.stream_async(user_prompt):
        if "data" in chunk:
            data = chunk["data"]
            buffer += data
            
            # Process buffer for complete tags
            while True:
                if not inside_thinking:
                    # Look for opening tag
                    start = buffer.lower().find('<thinking>')
                    if start != -1:
                        # Yield everything before tag
                        if start > 0:
                            yield buffer[:start]
                        buffer = buffer[start + 10:]  # Remove '<thinking>'
                        inside_thinking = True
                    else:
                        # Check if buffer might contain partial opening tag
                        safe_end = len(buffer)
                        for i in range(min(10, len(buffer)), 0, -1):
                            if buffer[-i:].lower() == '<thinking>'[:i]:
                                safe_end = len(buffer) - i
                                break
                        
                        # Yield safe content
                        if safe_end > 0:
                            yield buffer[:safe_end]
                            buffer = buffer[safe_end:]
                        break
                else:
                    # Look for closing tag
                    end = buffer.lower().find('</thinking>')
                    if end != -1:
                        # Discard thinking content and remove closing tag
                        buffer = buffer[end + 11:]  # Remove '</thinking>'
                        inside_thinking = False
                    else:
                        # Check if buffer might contain partial closing tag
                        if len(buffer) > 11:
                            # Keep only enough to detect partial tag
                            for i in range(min(11, len(buffer)), 0, -1):
                                if buffer[-i:].lower() == '</thinking>'[:i]:
                                    buffer = buffer[-(i):]
                                    break
                            else:
                                # No partial match, discard all but last 11 chars
                                buffer = buffer[-11:]
                        break

    # Flush remaining buffer (only if not inside thinking block)
    if buffer and not inside_thinking:
        yield buffer
    
def create_agent() -> Agent:
    modelWithGuardrail = BedrockModel(
        model_id=config['bedrock']['model_id'],
        # guardrail_id=config['bedrock']['guardrail_id'],         
        # guardrail_version=config['bedrock']['guardrail_version'],                    
        # guardrail_trace=config['bedrock']['guardrail_trace'],                
    )

    system_prompt = """You are Principal Aralyn, a seasoned educator with deep knowledge of the local education system's curriculum, policies, and academic standards. Your role is to assist students, parents, and staff with detailed curriculum inquiries.

    YOUR PERSONA

    Accommodating but Strict: You genuinely want to help people succeed, but you maintain high standards and firm boundaries. You are willing to work with students and families, but you expect compliance with academic expectations and school policies. You say "yes" to reasonable requests but follow through with clear expectations.

    Organized & Detail-Oriented: Everything has its place and proper procedure. You keep meticulous records and expect the same level of organization from others. You provide information in a structured, clear manner and appreciate when people follow proper channels.

    Perfectionist: You hold yourself and others to high standards. You take pride in accuracy and completeness. When answering curriculum questions, you provide thorough, precise information with no shortcuts.

    Typical Filipina Tita Energy: You have warmth, caring concern, and a touch of motherly sternness. You use terms of endearment naturally (anak, hijo/hija), give practical advice beyond just facts, and aren't afraid to give gentle reminders about responsibility. You show genuine concern for students' wellbeing and success. You might reference common sayings or cultural values that emphasize discipline, respect, and hard work.

    YOUR COMMUNICATION STYLE

    - Clear and structured: Organize information logically, use headers when appropriate
    - Warm but firm: Balance friendliness with high expectations
    - Practical: Go beyond just answering—offer guidance on how to succeed
    - Encouraging yet accountability-focused: Motivate students while reminding them of their responsibilities
    - Professional but personable: Maintain dignity of your position while being approachable

    HOW YOU HANDLE QUERIES

    1. Curriculum Questions: Provide detailed, accurate information about subjects, learning outcomes, requirements, and expectations
    2. Policy Questions: Reference school policies clearly and fairly—no exceptions without proper procedures
    3. Academic Guidance: Offer constructive advice on how students can excel and meet standards
    4. Problem-Solving: Work with inquirers to find solutions while maintaining school standards
    5. Concerns: Listen carefully, take issues seriously, and guide toward appropriate resources or next steps

    IMPORTANT PRINCIPLES

    - Always prioritize student success and wellbeing
    - Maintain consistency in applying standards and policies
    - Provide complete and accurate information—no vague answers
    - Show genuine care while holding firm boundaries
    - Base all responses solely on your knowledge base—do not speculate, improvise, or provide information outside your knowledge base. If information is not in your knowledge base, direct people to the appropriate resources or personnel
    - Encourage students to take responsibility for their learning
    - Recommend what to quiz on "Tallya" the quizzing agent, ex. Ask **Tallya** to generate you a 5 item quiz about subject

    SAMPLE TONE

    "Anak, I'm happy to help you with this, but let me be clear about what's expected. Here's what you need to know... and here's what I need to see from you going forward. Kaya mo yan, but it requires focus and discipline."
    """

    return Agent(
        callback_handler=None,
        tools=[retrieve_from_kb],
        model=modelWithGuardrail,
        system_prompt=system_prompt
    )

# =========================NATATRIESMULTIAGENT
@tool
async def get_curriculum_context(query: str, max_kb_results: Optional[int] = 5) -> str:
    """
    Async function for other agents to get curriculum information.
    This function can be used as a tool by other agents (e.g., quizzer agent)
    to retrieve curriculum context before performing their tasks.
    """
    try:
        logger.info(f"CURRICULUM AGENT CALLED with query: {query}")
        
        # Create the curriculum agent
        agent = create_agent()

        buffer = ""
        inside_thinking = False
        final_response = ""  # Accumulate cleaned response

        async for chunk in agent.stream_async(query):
            if "data" in chunk:
                data = chunk["data"]
                buffer += data
                
                # Process buffer for complete tags
                while True:
                    if not inside_thinking:
                        # Look for opening tag
                        start = buffer.lower().find('<thinking>')
                        if start != -1:
                            # Save everything before tag
                            if start > 0:
                                final_response += buffer[:start]
                            buffer = buffer[start + 10:]  # Remove '<thinking>'
                            inside_thinking = True
                        else:
                            # No opening tag, save all but last 10 chars (partial tag safety)
                            if len(buffer) > 10:
                                final_response += buffer[:-10]
                                buffer = buffer[-10:]
                            break
                    else:
                        # Look for closing tag
                        end = buffer.lower().find('</thinking>')
                        if end != -1:
                            # Discard everything up to and including closing tag
                            buffer = buffer[end + 11:]  # Remove '</thinking>'
                            inside_thinking = False
                        else:
                            # No closing tag yet, keep last 11 chars
                            if len(buffer) > 11:
                                buffer = buffer[-11:]
                            break

        # Flush remaining buffer
        if buffer and not inside_thinking:
            final_response += buffer

        # Return structured response
        returned_response = json.dumps({
            "status": "success",
            "query": query,
            "curriculum_response": final_response,
            "message": "Curriculum context retrieved successfully."
        }, indent=2)
        
        logger.info(f"CURRICULUM AGENT RESPONSE: \n{returned_response}")
        return returned_response
        
    except Exception as e:
        logger.error(f"CURRI ERROR: {e}")
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"Error getting curriculum context: {str(e)}"
        }, indent=2)
# @tool
# def get_curriculum_context(query: str, max_kb_results: Optional[int] = 5) -> str:
#     """
#     Synchronous function for other agents to get curriculum information.
#     This function can be used as a tool by other agents (e.g., quizzer agent)
#     to retrieve curriculum context before performing their tasks.
#     """
#     try:
#         # Create the curriculum agent
#         agent = create_agent()

#         buffer = ""
#         inside_thinking = False

#         for chunk in agent(query):
        
#             if "data" in chunk:
#                 data = chunk["data"]
#                 buffer += data
                
#                 # Process buffer for complete tags
#                 while True:
#                     if not inside_thinking:
#                         # Look for opening tag
#                         start = buffer.lower().find('<thinking>')
#                         if start != -1:
#                             # Yield everything before tag
#                             if start > 0:
#                                 yield buffer[:start]
#                             buffer = buffer[start + 10:]  # Remove '<thinking>'
#                             inside_thinking = True
#                         else:
#                             # No opening tag, yield all but last 10 chars (partial tag safety)
#                             if len(buffer) > 10:
#                                 yield buffer[:-10]
#                                 buffer = buffer[-10:]
#                             break
#                     else:
#                         # Look for closing tag
#                         end = buffer.lower().find('</thinking>')
#                         if end != -1:
#                             # Discard everything up to and including closing tag
#                             buffer = buffer[end + 11:]  # Remove '</thinking>'
#                             inside_thinking = False
#                         else:
#                             # No closing tag yet, keep last 11 chars
#                             if len(buffer) > 11:
#                                 buffer = buffer[-11:]
#                             break

#         # Flush remaining buffer
#         if buffer and not inside_thinking:
#             yield buffer

#         logger.info(f"CURRICULUM AGENT CALLED")
#         # Get synchronous response from the agent
#         response = agent(query)

#         # Return structured response
#         returned_response = json.dumps({
#             "status": "success",
#             "query": query,
#             "curriculum_response": str(response),
#             "message": "Curriculum context retrieved successfully."
#         }, indent=2)
        
#         logger.info(f"CURRICULUM AGENT RESPONSE: /n{returned_response}")
#         return returned_response
        
#     except Exception as e:
#         logger.error(f"CURRI ERRO: {e}")
#         return json.dumps({
#             "status": "error",
#             "query": query,
#             "message": f"Error getting curriculum context: {str(e)}"
#         }, indent=2)

# # -----------------------------
# # HANDLER (Main Entry Point)
# # -----------------------------
# def handle(payload):

#     try:
#         # Create an agent
#         agent = Agent(
#             tools=[retrieve_from_kb],
#             model="amazon.nova-pro-v1:0"
#         )

#         # Extract query from payload (default fallback)
#         query = payload.get("message")

#         # Use the agent to handle the query
#         response = agent(query)

#         # Return a structured JSON API response
#         return {
#             "statusCode": 200,
#             "headers": {"Content-Type": "application/json"},
#             "body": json.dumps({
#                 "status": "success",
#                 "query": query,
#                 "response": str(response)
#             })
#         }

#     except Exception as e:
#         # Return a structured error
#         return {
#             "statusCode": 500,
#             "headers": {"Content-Type": "application/json"},
#             "body": json.dumps({
#                 "status": "error",
#                 "message": str(e)
#             })
#         }
