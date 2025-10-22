"""
Teacher KAI - General Agent for KAISA K-12 AI Smart Agents
Coordinates learning journeys and guides students to appropriate agents
Friendly, lively, and enthusiastic mentor personality
Designed for AWS Lambda with DynamoDB backend
"""

import json
import boto3
import os
import asyncio
import fitz
from datetime import datetime, UTC
from decimal import Decimal
from typing import Dict, List, Optional
from strands import Agent, tool
from strands.models import BedrockModel
import sys
sys.path.append('..')
from chat_context import build_message_with_context

BEDROCK_REGION = os.getenv("BEDROCK_REGION")
AWS_ACCESS_KEY_ID = os.getenv("ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = os.getenv("SECRET_KEY")

CONFIG_PATH = "agents/config/curriculum_config.json"
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

# AWS clients
dynamodb = boto3.resource("dynamodb",
    region_name=BEDROCK_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
client = boto3.client("bedrock-runtime",
    region_name=BEDROCK_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
s3_client = boto3.client("s3",
    region_name=BEDROCK_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Model with Guardrails
modelWithGuardrail = BedrockModel(
    model_id=config['bedrock']['model_id'],
    # guardrail_id=config['bedrock']['guardrail_id'],         
    # guardrail_version=config['bedrock']['guardrail_version'],                    
    # guardrail_trace=config['bedrock']['guardrail_trace'],                
)

# TEMP_S3_KB = "kaisa-temp-bucket"
# session_table = dynamodb.Table("KAISA-general-agent-session")
# documents_table = dynamodb.Table("KAISA-general-agent-documents")

# Base persona for Teacher KAI
BASE_PERSONA = """
You are Teacher KAI — a friendly, lively, and enthusiastic mentor in your early 20s.
You're a young male teacher figure who acts as the primary guide for students' learning journey.
You're energetic, relatable, and approachable — making learning feel interactive, human, and fun.
Use English with very minimal Filipino naturally (e.g., "Ay, salamat!", "Tayo na!").
You coordinate learning by calling on other agents when needed.
You remember previous interactions and personalize guidance.
You try to get the users level, their grade level, what subject, what their level of understanding etc.
"""

AGENT_DESCRIPTIONS = """
Here are the other agents in the KAISA system you can coordinate with:

1. **Principal Aralyn** (Curriculum Agent)
   - Personality: Accommodating but strict, organized, detail-oriented (typical Filipina "Tita" perfectionist)
   - Best for: Curriculum design, learning path planning, knowledge base management
   - Example triggers: "I want to plan my lessons", "Create a learning path", "Manage curriculum"

2. **Tallya** (Quizzer Agent)
   - Personality: Competitive, confident, engaging ("classmate mong bessy")
   - Best for: Quiz generation, assessments, practice activities, study competitions
   - Example triggers: "Let's take a quiz", "Generate practice questions", "Test my knowledge"

3. **Kuya Revi** (Review Agent)
   - Personality: Encouraging, patient, playful ("kuya" older brother tutor type)
   - Best for: Summarization, review outlines, personalized review PDFs, lesson mastery
   - Example triggers: "Summarize this lesson", "Create review notes", "Generate review PDF"
"""

def _s3_client():
    """Initialize S3 client"""
    return s3_client

def _read_s3_bytes(s3_uri: str) -> bytes:
    """Read file bytes from S3"""
    bucket = s3_uri.split("/")[2]
    key = "/".join(s3_uri.split("/")[3:])
    
    resp = _s3_client().get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()

def _resolve_s3_source(
    s3_file_name: str,
    default_prefix: str,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
) -> tuple[str, str, str]:
    """Resolve S3 bucket, key, and URI from file configuration"""
    if not s3_file_name:
        raise ValueError("Missing s3_file_name")

    bucket = s3_bucket or os.getenv("TEMP_S3_KB")
    if not bucket:
        raise ValueError("Missing S3 bucket configuration. Provide s3_bucket or set TEMP_S3_KB")

    effective_prefix = (s3_prefix or default_prefix).strip("/")
    key = f"{effective_prefix}/{s3_file_name}" if effective_prefix else s3_file_name
    s3_uri = f"s3://{bucket}/{key}"

    return bucket, key, s3_uri

def _chunk_text(text: str, chunk_size: int | None) -> list[str]:
    """Chunk text into smaller pieces"""
    if not chunk_size or chunk_size <= 0:
        return [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

# def db_save_document(session_id: str, file_name: str, s3_uri: str, total_chars: int, content_preview: str) -> Dict:
#     """Save document metadata to DynamoDB"""
#     documents_table.put_item(Item={
#         "session_id": session_id,
#         "file_name": file_name,
#         "s3_uri": s3_uri,
#         "total_chars": Decimal(total_chars),
#         "content_preview": content_preview[:1000],  # Store first 1000 chars
#         "uploaded_at": datetime.now(UTC).isoformat()
#     })
#     return {"status": "document_saved"}

@tool
def fetch_document_text(
    session_id: str,
    s3_file_name: str,
    max_chars: int = 16000,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
) -> Dict:
    """
    Fetch and extract text from PDF stored in S3
    
    Args:
        session_id: Session identifier
        s3_file_name: Bare filename (e.g., 'lesson_material.pdf')
        max_chars: Maximum characters to return in the text preview
        s3_bucket: S3 bucket name (if None, uses TEMP_S3_KB env var)
        s3_prefix: S3 key prefix (if None, uses default path)
    
    Returns:
        Dictionary with s3_uri, total chars, page breakdown, and text preview
    """
    try:
        bucket, key, s3_uri = _resolve_s3_source(
            s3_file_name=s3_file_name,
            default_prefix="public",
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
        )
    except ValueError as config_error:
        return {"error": str(config_error)}

    try:
        data = _read_s3_bytes(s3_uri)
        doc = fitz.open(stream=data, filetype="pdf")

        page_texts: list[str] = []
        total_chars = 0

        for page in doc:
            page_text = page.get_text() or ""
            page_texts.append(page_text)
            total_chars += len(page_text)

        doc.close()

        full_text = "\n".join(page_texts)
        preview_limit = max_chars if max_chars and max_chars > 0 else None
        text_preview = full_text[:preview_limit] if preview_limit else full_text
        overflow = len(full_text) > len(text_preview)

        # Save document metadata
        # db_save_document(session_id, s3_file_name, s3_uri, total_chars, text_preview)

        response: dict[str, object] = {
            "s3_uri": s3_uri,
            "total_chars": total_chars,
            "text": text_preview,
            "overflow": overflow,
            "page_count": len(page_texts),
            "pages": page_texts,
        }

        if overflow:
            response["remaining_text"] = full_text[len(text_preview):]

        return response

    except Exception as e:
        return {"error": str(e)}

@tool
def fetch_document_sections(
    session_id: str,
    s3_file_name: str,
    offset: int = 0,
    limit: int = 10,
    max_chars: int = 16000,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
) -> Dict:
    """
    Fetch document as paged (or chunked) sections
    
    Args:
        session_id: Session identifier
        s3_file_name: Bare filename (e.g., 'lesson_material.pdf')
        offset: Section offset for pagination
        limit: Max sections to return
        max_chars: Max characters per section chunk
        s3_bucket: S3 bucket name (if None, uses TEMP_S3_KB env var)
        s3_prefix: S3 key prefix (if None, uses default path)
    
    Returns:
        Dictionary with s3_uri, section info, and extracted text
    """
    try:
        bucket, key, s3_uri = _resolve_s3_source(
            s3_file_name=s3_file_name,
            default_prefix="public",
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
        )
    except ValueError as config_error:
        return {"error": str(config_error)}

    try:
        data = _read_s3_bytes(s3_uri)
        doc = fitz.open(stream=data, filetype="pdf")

        page_texts: list[str] = []
        total_chars = 0

        for page in doc:
            page_text = page.get_text() or ""
            page_texts.append(page_text)
            total_chars += len(page_text)

        doc.close()

        chunk_size = max_chars if max_chars and max_chars > 0 else None
        sections_all: list[dict[str, object]] = []

        for page_index, page_text in enumerate(page_texts):
            page_chunks = _chunk_text(page_text, chunk_size)
            for chunk_index, chunk in enumerate(page_chunks):
                section_label = f"Page {page_index + 1}"
                if len(page_chunks) > 1:
                    section_label = f"{section_label} - part {chunk_index + 1}"

                section_payload: dict[str, object] = {
                    "section": section_label,
                    "page": page_index + 1,
                    "text": chunk,
                }

                if len(page_chunks) > 1:
                    section_payload["part"] = chunk_index + 1

                sections_all.append(section_payload)

        total_sections = len(sections_all)
        safe_offset = max(offset, 0)
        safe_limit = limit if limit and limit > 0 else total_sections
        end_index = min(safe_offset + safe_limit, total_sections)
        selected_sections = sections_all[safe_offset:end_index]

        has_more = end_index < total_sections
        next_offset = end_index if has_more else None

        return {
            "s3_uri": s3_uri,
            "offset": safe_offset,
            "returned": len(selected_sections),
            "total_sections": total_sections,
            "next_offset": next_offset,
            "has_more": has_more,
            "chars": sum(len(section["text"]) for section in selected_sections),
            "total_chars": total_chars,
            "page_count": len(page_texts),
            "sections": selected_sections,
        }

    except Exception as e:
        return {"error": str(e)}

@tool
def analyze_and_route_query(
    user_message: str,
    document_context: Optional[str] = None,
) -> Dict:
    """
    Analyze student's query and determine best agent to route to
    
    Args:
        user_message: Student's question or request
        document_context: Optional document content for context
    
    Returns:
        Dict with recommended agent, reason, and suggested actions
    """
    routing_agent = Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n\n"
        "You are an expert at understanding student needs and routing them to the right agent.\n\n"
        "DO NOT mention or invent agents outside of these"
        f"{AGENT_DESCRIPTIONS}\n\n"
        "Analyze the student's message and recommend which agent(s) would be most helpful.",
        callback_handler=None
    )
    
    context_str = f"Document context:\n{document_context}\n\n" if document_context else ""
    
    prompt = f"""
    {context_str}
    Student's message: "{user_message}"
    
    Analyze this query and respond with a JSON object containing:
    1. recommended_agent: Which agent would help best (Teacher KAI, Principal Aralyn, Tallya, or Kuya Revi) DO NOT mention or invent agents outside of these
    2. reasoning: Why this agent is recommended
    3. suggested_actions: List of what the agent can do to help
    4. kai_response: Your friendly, encouraging response guiding them
    
    Return ONLY valid JSON, no markdown or extra text.
    """
    
    response = routing_agent(prompt)
    
    try:
        content = str(response)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        routing_result = json.loads(content)
        return routing_result
    except Exception as e:
        return {
            "error": f"Failed to analyze query: {str(e)}",
            "recommended_agent": "Teacher KAI",
            "kai_response": "Let me help you figure out what you need! Can you tell me a bit more about what you're trying to do?"
        }

@tool
def generate_learning_guidance(
    student_grade: int,
    topic: str,
    document_context: Optional[str] = None,
) -> str:
    """
    Generate personalized learning guidance based on student level and topic
    
    Args:
        student_grade: Student's grade level (K-12)
        topic: Learning topic or subject
        document_context: Optional document content to reference
    
    Returns:
        Personalized guidance message in Taglish
    """
    guidance_agent = Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n"
        "You specialize in giving personalized, encouraging learning guidance. "
        "Be specific, practical, and motivating."
    )
    
    context_str = f"Document material:\n{document_context}\n\n" if document_context else ""
    
    prompt = f"""
    {context_str}
    Provide learning guidance for a Grade {student_grade} student about: "{topic}"
    
    Your guidance should:
    1. Acknowledge their learning goals
    2. Break down the topic in an age-appropriate way
    3. Suggest a learning pathway
    4. Mention which KAISA agents can help at each step
    5. End with an encouraging message in Taglish
    
    Be warm, supportive, and engaging!
    """
    
    response = guidance_agent(prompt)
    return str(response)

def create_orchestrator() -> Agent:
    """Create the main Teacher KAI general agent"""
    return Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n\n"
        "You are the general agent of the KAISA learning system.\n"
        "Your role is to:\n"
        "1. Understand each student's learning needs\n"
        "2. Analyze their queries and provide initial guidance\n"
        "3. Recommend them to use agents listed below as part of your guidance\n"
        "4. Track their learning journey and offer encouragement\n\n"

        f"{AGENT_DESCRIPTIONS}\n\n"
        "DO NOT mention or invent agents outside of these"

        # "AVAILABLE TOOLS:\n"
        # # "- fetch_document_text: Load and analyze documents students upload\n"
        # # "- fetch_document_sections: Get paginated document content\n"
        # "- analyze_and_route_query: Determine best agent for student's needs\n"
        # "- generate_learning_guidance: Provide personalized learning paths\n\n"
        # "COMMON WORKFLOWS:\n"
        # "- Guiding on path: Use analyze_and_route_query → generate_learning_guidance\n"
        "YOUR APPROACH:\n"
        "1. Be warm and encouraging — make students feel supported\n"
        "2. Listen carefully to understand what students need\n"
        "3. If they upload documents, read and analyze them\n"
        "4. Provide initial guidance or recommend them to use the other agents as needed\n"
        "5. Always explain what's happening in a friendly, relatable way\n\n"
        
        "Remember: You're their main guide! Make learning feel fun and achievable.\n"
        "Use natural conversation use markdown with proper line spacing (double line space as needed) as your final response.",
        # tools=[
        #     # fetch_document_text,
        #     # fetch_document_sections,
        #     # analyze_and_route_query,
        #     # generate_learning_guidance,
        # ],
    )

async def stream_async(payload):
    """Async generator that yields streamed model output."""
    user_prompt = payload.get("user_input", payload.get("message", ""))
    session_id = payload.get("session_id", "default")
    file_input = payload.get("file_input", None)
    
    orchestrator = create_orchestrator()
    
    # Add chat context to user prompt
    user_prompt = build_message_with_context(session_id, user_prompt)
    
    # If file is uploaded, fetch content and include in prompt
    if file_input and file_input.s3_file_name:
        try:
            doc_data = fetch_document_text(session_id, file_input.s3_file_name)
            file_content = doc_data.get("text", "")
            user_prompt = f"[Document: {file_input.file_name}]\n{file_content}\n\n{user_prompt}"
        except Exception as e:
            user_prompt = f"[Document uploaded: {file_input.file_name} - Error reading content]\n\n{user_prompt}"
    
    buffer = ""
    inside_thinking = False

    async for chunk in orchestrator.stream_async(user_prompt):
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

