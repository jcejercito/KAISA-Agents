"""
Tallya Quizzer Agent - Multi-Agent Quiz System using Strands SDK
Orchestrator-driven architecture where the agent decides what to do
Database operations handled separately - tools focus on business logic
Designed for AWS Lambda with DynamoDB backend
"""

import json
import boto3
import os
import asyncio
from datetime import datetime, UTC
from decimal import Decimal
from typing import Dict, List, Optional
from strands import Agent, tool
from strands.models import BedrockModel
import sys
sys.path.append('..')
from chat_context import build_message_with_context
from agents import curriculum_agent, review_agent, general_agent
from agents.curriculum_agent import get_curriculum_context

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


BEDROCK_REGION = os.getenv("BEDROCK_REGION")
AWS_ACCESS_KEY_ID = os.getenv("ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = os.getenv("SECRET_KEY")
KNOWLEDGE_BASE_ID = os.getenv("KB_ID")

CONFIG_PATH = "agents/config/quizzer_config.json"
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
quiz_table = dynamodb.Table("KAISA-quiz-agent-qna")
session_table = dynamodb.Table("KAISA-quiz-agent-quiz-session")

# Base persona for all Tallya agents
BASE_PERSONA = """
You are Tallya — a competitive, confident, and helpful K–12 classmate.
Be supportive, in English with little hints of tagalog(e.g., "Ang galing mo, Bessy!").
When explaining, be structured but fun.
You remember what we talked about earlier in the session.
"""

# Model with Guardrails
modelWithGuardrail = BedrockModel(
    model_id=config['bedrock']['model_id'],
    # guardrail_id=config['bedrock']['guardrail_id'],         
    # guardrail_version=config['bedrock']['guardrail_version'],                    
    # guardrail_trace=config['bedrock']['guardrail_trace'],                
)

def db_save_quiz(session_id: str, quiz_items: List[Dict], topic: str, grade: int) -> Dict:
    """Save quiz items to DynamoDB"""
    for i, q in enumerate(quiz_items):
        quiz_table.put_item(Item={
            "session_id": session_id,
            "q_index": i,
            "question": q["question"],
            "options": q["options"],
            "correct": q["correct"],
            "explanation": q.get("explanation", ""),
            "topic": topic,
            "grade": grade,
            "created_at": datetime.now(UTC).isoformat()
        })
    return {"items_saved": len(quiz_items)}

@tool
def db_get_question(session_id: str, q_index: int) -> Dict:
    """Retrieve a question from DynamoDB"""
    res = quiz_table.get_item(Key={"session_id": session_id, "q_index": q_index})
    item = res.get("Item")
    if not item:
        return {"error": "Question not found"}
    return {
        "question": item["question"],
        "options": item["options"],
        "correct": item["correct"],
        "explanation": item.get("explanation", ""),
        "topic": item.get("topic", ""),
        "grade": item.get("grade", 0),
        "user_answer": item.get("user_answer", "")
    }


def db_update_question_answer(session_id: str, q_index: int, user_answer: str, is_correct: bool) -> Dict:
    """Update question with user's answer in DynamoDB"""
    status = "correct" if is_correct else "wrong"
    quiz_table.update_item(
        Key={"session_id": session_id, "q_index": q_index},
        UpdateExpression="SET user_answer=:a, score_status=:s, answered_at=:t",
        ExpressionAttributeValues={
            ":a": user_answer.upper(),
            ":s": status,
            ":t": datetime.now(UTC).isoformat()
        }
    )
    return {"status": "updated"}

@tool
def db_get_session(session_id: str) -> Dict:
    """Retrieve session data from DynamoDB"""
    res = session_table.get_item(Key={"session_id": session_id})
    session = res.get("Item")
    if not session:
        return {"error": "Session not found"}
    
    return {
        "session_id": session_id,
        "state": session.get("state", ""),
        "current_question": int(session.get("current_question", 0)),
        "total_questions": int(session.get("total_questions", 0)),
        "score": int(session.get("score", 0)),
        "topic": session.get("topic", ""),
        "grade": int(session.get("grade", 0)),
        "history": session.get("history", []),
        "started_at": session.get("started_at", ""),
        "updated_at": session.get("updated_at", "")
    }


def db_update_session_progress(
    session_id: str,
    score: Optional[int] = None,
    current_question: Optional[int] = None,
    state: Optional[str] = None
) -> Dict:
    """Update session progress in DynamoDB"""
    update_parts = ["updated_at=:u"]
    expr_values = {":u": datetime.now(UTC).isoformat()}
    expr_names = {}
    
    if score is not None:
        update_parts.append("score=:sc")
        expr_values[":sc"] = Decimal(score)
    
    if current_question is not None:
        update_parts.append("current_question=:cq")
        expr_values[":cq"] = Decimal(current_question)
    
    if state is not None:
        update_parts.append("#state=:st")
        expr_values[":st"] = state
        expr_names["#state"] = "state"
    
    update_expr = "SET " + ", ".join(update_parts)
    
    kwargs = {
        "Key": {"session_id": session_id},
        "UpdateExpression": update_expr,
        "ExpressionAttributeValues": expr_values
    }
    
    if expr_names:
        kwargs["ExpressionAttributeNames"] = expr_names
    
    session_table.update_item(**kwargs)
    return {"status": "updated"}


def db_create_session(
    session_id: str,
    total_questions: int,
    topic: str,
    grade: int
) -> Dict:
    """Create a new session in DynamoDB"""
    session_table.put_item(Item={
        "session_id": session_id,
        "current_question": 0,
        "total_questions": total_questions,
        "score": 0,
        "history": [],
        "state": "in_progress",
        "topic": topic,
        "grade": grade,
        "started_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat()
    })
    return {"status": "created"}


def db_add_to_chat_history(session_id: str, student_message: str, tallya_reply: str) -> Dict:
    """Add conversation turn to session history in DynamoDB"""
    session = session_table.get_item(Key={"session_id": session_id}).get("Item")
    
    if not session:
        return {"error": "Session not found"}
    
    history = session.get("history", [])
    history.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "student": student_message,
        "tallya": tallya_reply
    })
    
    session_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET history=:h, updated_at=:u",
        ExpressionAttributeValues={
            ":h": history[-20:],
            ":u": datetime.now(UTC).isoformat()
        }
    )
    return {"status": "history_updated"}


@tool
def generate_quiz_questions(session_id, topic: str, grade: int, num_questions: int) -> List[Dict]:
    """
    Generate quiz questions for a given topic and grade level.
    Returns educational content - no database operations.
    
    Args:
        session_id: Session identifier
        topic: The subject or topic for the quiz
        grade: Student grade level (K-12)
        num_questions: Number of questions to generate
    
    Returns:
        List of question dictionaries with question, options, correct answer, and explanation
    """
    quiz_gen_agent = Agent(
        callback_handler=None,
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n"
        "You are an expert at creating educational quiz questions. "
        "Generate engaging, age-appropriate multiple-choice questions. "
        "Each question must have exactly 4 options (A, B, C, D) with one correct answer."
    )
    
    prompt = f"""
    Generate {num_questions} multiple-choice questions for Grade {grade} students about: "{topic}"
    
    Requirements:
    - Age-appropriate for Grade {grade}
    - Exactly 4 options labeled A, B, C, D
    - One clearly correct answer
    - Include brief explanation
    - Make it engaging and educational
    
    Return ONLY a valid JSON array in this exact format:
    [
      {{
        "question": "What is the capital of the Philippines?",
        "options": {{
          "A": "Manila",
          "B": "Cebu",
          "C": "Davao",
          "D": "Quezon City"
        }},
        "correct": "A",
        "explanation": "Manila is the capital city of the Philippines."
      }}
    ]
    """
    print(f"Generating Quiz Questions")
    print("\n" + "="*50 + "\n")
    
    response = quiz_gen_agent(prompt)
    
    # Parse JSON from response
    try:
        content = str(response)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        import re
        json_match = re.search(r'\[.*?\]', content, re.DOTALL)
        if json_match:
            quiz_items = json.loads(json_match.group(0))
        else:
            quiz_items = json.loads(content)
        db_save_quiz(session_id, quiz_items, topic, grade)
        db_create_session(session_id, len(quiz_items), topic, grade)
        return quiz_items
    
    except Exception as e:
        return [{"error": f"Failed to generate quiz: {str(e)}"}]



@tool
def evaluate_answer(
    session_id,
    q_index: int,
    question: str,
    options: Dict,
    correct_answer: str,
    user_answer: str
) -> Dict:
    """
    Evaluate if a student's answer is correct.
    Pure business logic - returns correctness assessment.
    
    Args:
        question: The quiz question
        options: Dict of answer options (A, B, C, D)
        correct_answer: The correct answer letter
        user_answer: Student's answer letter
    
    Returns:
        Dict with is_correct and normalized answers
    """
    user_ans_normalized = user_answer.upper().strip()
    correct_ans_normalized = correct_answer.upper().strip()

    db_update_question_answer(session_id, q_index, user_answer, user_ans_normalized == correct_ans_normalized)
                
    # Update session progress
    session_data = db_get_session(session_id)
    new_score = session_data["score"] + (1 if user_ans_normalized == correct_ans_normalized else 0)
    new_question = session_data["current_question"] + 1
    new_state = "completed" if new_question >= session_data["total_questions"] else "in_progress"
    
    db_update_session_progress(session_id, score=new_score, current_question=new_question, state=new_state)
    
    return {
        "is_correct": user_ans_normalized == correct_ans_normalized,
        "user_answer": user_ans_normalized,
        "correct_answer": correct_ans_normalized,
        "user_choice_text": options.get(user_ans_normalized, "Invalid"),
        "correct_choice_text": options.get(correct_ans_normalized, "")
    }


@tool
def generate_feedback(
    question: str,
    options: Dict,
    correct_answer: str,
    user_answer: str,
    is_correct: bool,
    explanation: str
) -> str:
    """
    Generate encouraging feedback for a student's answer.
    Pure content generation - no database operations.
    
    Args:
        question: The quiz question
        options: Dict of answer options (A, B, C, D)
        correct_answer: The correct answer letter
        user_answer: Student's answer letter
        is_correct: Whether the answer was correct
        explanation: Explanation of the correct answer
    
    Returns:
        Personalized feedback string in Taglish
    """
    feedback_agent = Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n"
        "You specialize in giving encouraging, educational feedback. "
        "Mix English and Filipino naturally. Be supportive and helpful."
    )
    
    status = "CORRECT! 🎉" if is_correct else "Wrong 😞"
    
    prompt = f"""
    Give feedback for this answer:
    
    Question: {question}
    Options: {json.dumps(options, ensure_ascii=False)}
    Student answered: {user_answer}
    Correct answer: {correct_answer} - {options.get(correct_answer, '')}
    Result: {status}
    Explanation: {explanation}
    
    Provide encouraging feedback in 2-3 sentences:
    1. Acknowledge if correct (celebrate!) or explain why it's wrong
    2. Give a helpful tip or clarify the correct answer
    3. Encourage them for the next question
    
    Use Taglish naturally (mix English and Filipino).
    Be warm, supportive, and educational!
    """
    print(f"Generating Feedback")
    print("\n" + "="*50 + "\n")

    feedback = feedback_agent(prompt)
    return str(feedback)


@tool
def generate_explanation(
    question: str,
    options: Dict,
    correct_answer: str,
    topic: str,
    grade: int,
    specific_concept: Optional[str] = None
) -> str:
    """
    Generate a detailed step-by-step explanation of a concept.
    Pure content generation - no database operations.
    
    Args:
        question: The quiz question
        options: Dict of answer options
        correct_answer: The correct answer letter
        topic: The quiz topic
        grade: Student grade level
        specific_concept: Specific aspect the student asks about (optional)
    
    Returns:
        Detailed explanation string in Taglish
    """

    print(f"Generating Explanation")
    print("\n" + "="*50 + "\n")

    explain_agent = Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n"
        "You are an expert at explaining complex concepts simply. "
        "Break things down step-by-step for K-12 students. "
        "Use examples, analogies, and mnemonics."
    )
    
    prompt = f"""
    Explain this concept in detail:
    
    Question: {question}
    Correct Answer: {correct_answer} - {options.get(correct_answer, '')}
    Topic: {topic}
    Grade Level: {grade}
    {"Student asks specifically about: " + specific_concept if specific_concept else ""}
    
    Provide a comprehensive explanation:
    1. Restate the question in simple terms
    2. Break down the concept into easy-to-understand parts
    3. Explain why the correct answer makes sense
    4. Give a real-world example or helpful mnemonic
    5. End with an encouraging tip
    
    Use Taglish naturally. Be conversational and engaging!
    Make it easy for a Grade {grade} student to understand.
    """
    
    explanation = explain_agent(prompt)
    return str(explanation)


@tool
def generate_chat_response(
    session_id,
    current_progress: Dict,
    chat_history: List[Dict],
    student_message: str
) -> str:
    """
    Generate contextual chat response based on quiz progress.
    Pure response generation - no database operations.
    
    Args:
        current_progress: Current session progress (score, question, state)
        chat_history: Recent conversation history
        student_message: The student's latest message
    
    Returns:
        Contextual response from Tallya in Taglish
    """
    chat_agent = Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n"
        "You maintain conversational context and respond naturally to student messages. "
        "Reference their quiz progress and previous interactions when relevant."
    )
    
    progress_str = json.dumps(current_progress, indent=2)
    history_str = json.dumps(chat_history[-5:], indent=2, ensure_ascii=False) if chat_history else "[]"
    
    prompt = f"""
    Respond naturally to the student's message.
    
    Current Progress:
    {progress_str}
    
    Recent Chat History (last 5 messages):
    {history_str}
    
    Student's message: "{student_message}"
    
    Respond as Tallya:
    - Be supportive and encouraging
    - Reference their quiz progress if relevant
    - Mix English and Filipino naturally
    - Keep it friendly and conversational
    - Be helpful with their quiz journey
    get_curriculum_context
    Just respond naturally - be conversational!
    """

    print(f"Generating Chat Response")
    print("\n" + "="*50 + "\n")
    
    response = chat_agent(prompt)
    db_add_to_chat_history(session_id, student_message, response)
    return str(response)

def create_orchestrator() -> Agent:
    return Agent(
        model=modelWithGuardrail,
        system_prompt=f"{BASE_PERSONA}\n\n"
        "You are the MASTER ORCHESTRATOR of the Tallya Quiz System.\n"
        "Your role is to analyze user requests and decide what actions to take.\n\n"
        "AVAILABLE TOOLS:\n"
        "- generate_quiz_questions: Create quiz content\n"
        "- db_get_question: To get more context of the question, answer, and explanation\n"
        "- evaluate_answer: Check if an answer is correct\n"
        "- get_curriculum_context: This calls curriculum agent, needed whenever there is query about curriculums. Always use this before quiz generation.\n"
        "- generate_feedback: Create personalized feedback\n"
        "- generate_explanation: Provide detailed explanations\n"
        "- generate_chat_response: Create contextual chat responses\n\n"
        "YOUR WORKFLOW:\n"
        "1. Analyze the user's request\n"
        "2. Determine the action needed (quiz generation, answer checking, explanation, chat, status)\n"
        "3. Call the appropriate tools\n"
        "4. Return a complete, structured response\n\n"
        "COMMON WORKFLOWS:\n"
        "- Quiz Generation: Use get_curriculum_context → generate_quiz_questions → only show the questions DO NOT SHOW answers and explanation Use double line spacing\n"
        "- Answer Submission: Use db_get_question → evaluate_answer → generate_feedback\n"
        "- Explanation Request: Use db_get_question → generate_explanation\n"
        "- Chat: Use db_get_session → generate_chat_response\n"
        "- Status Check: Use db_get_session → Return progress from input data\n\n"
        "BE INTELLIGENT: Understand context, infer intent, and provide complete solutions.\n"
        "ALWAYS use tools to generate content - don't make up data without calling tools first!\n"
        "Use natural conversation with headers and with proper line spacing (double line space before a header) as your final response."
        "For quiz generation, make the questions as headers",
        tools=[
            generate_quiz_questions,
            evaluate_answer,
            generate_feedback,
            generate_explanation,
            generate_chat_response,
            get_curriculum_context,
            db_get_question,
            db_get_session,
        ],
    )

async def stream_async(payload):
    """Async generator that yields streamed model output."""
    user_prompt = payload.get("user_input", payload.get("message", ""))
    file_input = payload.get("file_input", None)
    session_id = payload.get("session_id")
    user_prompt = build_message_with_context(session_id, user_prompt)
    
    # If file is uploaded, include file info in prompt
    if file_input and file_input.file_name:
        user_prompt = f"[Document attached: {file_input.file_name}]\n\n{user_prompt}"
    tallya = create_orchestrator()

    logger.info(f"QUIZZER AGENT CALLED")

    buffer = ""
    inside_thinking = False

    async for chunk in tallya.stream_async(user_prompt):
        if "data" in chunk:
            data = chunk["data"]
            buffer += data
            
            # Process buffer for complete tags
            while True:
                if not inside_thinking:
                    # Look for opening tag
                    start = buffer.lower().find('<thinking>')
                    if start != -1:
                        # Yield everything before tag, converting newlines
                        if start > 0:
                            yield buffer[:start].replace('\n', '<br>')
                        buffer = buffer[start + 10:]
                        inside_thinking = True
                    else:
                        # Check if buffer might contain partial opening tag
                        safe_end = len(buffer)
                        for i in range(min(10, len(buffer)), 0, -1):
                            if buffer[-i:].lower() == '<thinking>'[:i]:
                                safe_end = len(buffer) - i
                                break
                        
                        # Yield safe content with newlines converted to <br>
                        if safe_end > 0:
                            yield buffer[:safe_end].replace('\n', '<br>')
                            buffer = buffer[safe_end:]
                        break
                else:
                    # Look for closing tag
                    end = buffer.lower().find('</thinking>')
                    if end != -1:
                        buffer = buffer[end + 11:]
                        inside_thinking = False
                    else:
                        if len(buffer) > 11:
                            for i in range(min(11, len(buffer)), 0, -1):
                                if buffer[-i:].lower() == '</thinking>'[:i]:
                                    buffer = buffer[-(i):]
                                    break
                            else:
                                buffer = buffer[-11:]
                        break

    # Flush remaining buffer with newlines converted
    if buffer and not inside_thinking:
        yield buffer.replace('\n', '<br>')

        # if hasattr(chunk, "text"):
        #     yield chunk.text
        # else:
        #     yield str(chunk)
        # if "data" in chunk:
        #     data = chunk["data"]
        #     thinking_parts = ["<", "<t", "<th", "<thi", "<thin", "<think", "<thinki", "<thinkin", "<thinking", "<thinking>", 
        #                      "</", "</t", "</th", "</thi", "</thin", "</think", "</thinki", "</thinkin", "</thinking", "</thinking>"]
        #     if not any(part in data.lower() for part in thinking_parts):
        #         yield data
        # else:
        #     yield str(chunk)

# async def handle(body):
#     """
#     AWS Lambda entry point
#     - Orchestrator handles business logic
#     - Separate database operations
#     """

#     orchestrator = create_orchestrator()

#     # orchestrator = Agent(
#     #     # callback_handler=None,
#     #     model=modelWithGuardrail,
#     #     system_prompt=f"{BASE_PERSONA}\n\n"
#     #     "You are the MASTER ORCHESTRATOR of the Tallya Quiz System.\n"
#     #     "Your role is to analyze user requests and decide what actions to take.\n\n"
        
#     #     "AVAILABLE TOOLS:\n"
#     #     "- generate_quiz_questions: Create quiz content\n"
#     #     "- db_get_question: To get more context of the question, answer, and explanation\n"
#     #     "- evaluate_answer: Check if an answer is correct\n"
#     #     "- generate_feedback: Create personalized feedback\n"
#     #     "- generate_explanation: Provide detailed explanations\n"
#     #     "- generate_chat_response: Create contextual chat responses\n\n"
        
#     #     "YOUR WORKFLOW:\n"
#     #     "1. Analyze the user's request\n"
#     #     "2. Determine the action needed (quiz generation, answer checking, explanation, chat, status)\n"
#     #     "3. Call the appropriate tools\n"
#     #     "4. Return a complete, structured response\n\n"
        
#     #     "COMMON WORKFLOWS:\n"
#     #     "- Quiz Generation: Use generate_quiz_questions\n"
#     #     "- Answer Submission: Use db_get_question → evaluate_answer → generate_feedback\n"
#     #     "- Explanation Request: Use db_get_question → generate_explanation\n"
#     #     "- Chat: Use db_get_session → generate_chat_response\n"
#     #     "- Status Check: Use db_get_session → Return progress from input data\n\n"
        
#     #     "BE INTELLIGENT: Understand context, infer intent, and provide complete solutions.\n"
#     #     "ALWAYS use tools to generate content - don't make up data without calling tools first!\n"
#     #     "Return your final response as a clean JSON object.",
        
#     #     tools=[
#     #         generate_quiz_questions,
#     #         evaluate_answer,
#     #         generate_feedback,
#     #         generate_explanation,
#     #         generate_chat_response,
#     #         db_get_question,
#     #         db_get_session
#     #     ]
#     # )
    
#     try:
        
#         # Generate session ID if not provided
#         session_id = body.get("session_id", f"session-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
        
#         # Add session_id to body if not present
#         if "session_id" not in body:
#             body["session_id"] = session_id
        
#         # Create a natural language request for the orchestrator
#         request_prompt = f"""
#         USER REQUEST:
#         {json.dumps(body, indent=2, ensure_ascii=False)}
        
#         SESSION_ID: {session_id}
#         TIMESTAMP: {datetime.now(UTC).isoformat()}
        
#         Analyze this request and determine what the user wants:
#         - If they mention "quiz", "generate", "create", "start": Generate quiz content
#         - If they mention "answer", "submit", "check": Evaluate their answer
#         - If they mention "explain", "help", "understand": Provide explanation
#         - If they mention "chat", "talk", "hello": Respond conversationally
#         - If they mention "status", "progress": Return their progress
        
#         Call the appropriate tools and return a complete response.
#         """

#         # Stream from the model
#         streamed_text = ""
#         async for chunk in orchestrator.stream_async(request_prompt):
#             text_chunk = str(chunk)
#             streamed_text += text_chunk
#             yield text_chunk  # Send to WebSocket in real time

#         # 🧩 Once streaming completes, parse JSON content from full text
#         # try:
#         #     response_text = streamed_text.strip()
#         #     if "```json" in response_text:
#         #         json_content = response_text.split("```json")[1].split("```")[0].strip()
#         #     elif "{" in response_text and "}" in response_text:
#         #         import re
#         #         json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
#         #         json_content = json_match.group(0) if json_match else "{}"
#         #     else:
#         #         json_content = "{}"

#         #     final_json = json.loads(json_content)
#         # except Exception:
#         #     final_json = {"session_id": session_id, "response": streamed_text, "status": "completed"}

#         # # Yield final structured result
#         # yield json.dumps({"type": "final", "data": final_json})

#         if "```json" in response_text:
#             json_content = response_text.split("```json")[1].split("```")[0].strip()
#         elif "{" in response_text and "}" in response_text:
#             import re
#             json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
#             json_content = json_match.group(0) if json_match else "{}"
#         else:
#             json_content = "{}"

#         final_json = json.loads(json_content)
#         yield json.dumps({"type": "final", "data": final_json})

#     except Exception as exc:
#         import traceback

#         error_payload = {
#             "type": type(exc).__name__,
#             "message": str(exc),
#             "traceback": traceback.format_exc(),
#             "session_id": body.get("session_id"),
#         }

#         yield json.dumps({"type": "error", "data": error_payload})
#         raise
        
#     #     # Let the orchestrator decide and execute
#     #     orchestrator_response = orchestrator(request_prompt)
        
#     #     # Parse orchestrator's response
#     #     try:
#     #         response_text = str(orchestrator_response)
            
#     #         # Extract JSON from response
#     #         if "```json" in response_text:
#     #             json_content = response_text.split("```json")[1].split("```")[0].strip()
#     #         elif "```" in response_text:
#     #             json_content = response_text.split("```")[1].split("```")[0].strip()
#     #         elif "{" in response_text and "}" in response_text:
#     #             import re
#     #             json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
#     #             json_content = json_match.group(0) if json_match else response_text
#     #         else:
#     #             json_content = response_text
            
#     #         result = json.loads(json_content)
#     #     except:
#     #         result = {
#     #             "session_id": session_id,
#     #             "response": str(orchestrator_response),
#     #             "status": "completed"
#     #         }
    
#     # except Exception as e:
#     #     import traceback
#     #     return {
#     #         "statusCode": 500,
#     #         "body": json.dumps({
#     #             "error": str(e),
#     #             "type": type(e).__name__,
#     #             "traceback": traceback.format_exc()
#     #         })
#     #     }

