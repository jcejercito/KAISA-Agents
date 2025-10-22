import boto3, os, html, traceback, json, re
from datetime import datetime

def get_outline_and_notes(query: str, isPDF: str = "true", mode: str = "friendly") -> str:
    """
    Retrieve topic content from the Knowledge Base and generate a full reviewer outline
    with expanded explanations per subtopic. Produces detailed, readable study material.
    """

    CONFIG_PATH = "config.json"
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    kb_id = os.getenv("BEDROCK_KB_ID", config['kb']['id'])
    kb_model_arn = os.getenv("BEDROCK_MODEL_ARN", config['kb']['model_embed'])

    try:
        # --- Step 1: Retrieve base KB content ---
        bedrock = boto3.client("bedrock-agent-runtime", region_name=config['aws_region'])
        response = bedrock.retrieve_and_generate(
            input={"text": query},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": kb_id,
                    "modelArn": kb_model_arn
                }
            }
        )

        kb_text = response.get("output", {}).get("text", "").strip()
        kb_text = html.unescape(kb_text)

        # --- Step 2: Generate the detailed reviewer content ---
        bedrock_llm = boto3.client("bedrock-runtime", region_name=config['aws_region'])
        maxTokens = 8000 if isPDF == "true" else 1000

        prompt = f"""
        You are a licensed Senior High School teacher writing a **complete DepEd-style reviewer**.
        
        Use the Knowledge Base content below as your factual reference.
        Write in a structured format, but be detailed and thorough in each section — aim for several sentences per part, not just short phrases.
        
        Respond in this exact JSON format:
        {{
          "Lesson Overview": "A few paragraphs explaining what the lesson is about and why it matters.",
          "Learning Objectives": [
            "Explain clearly what students will be able to do after studying this topic.",
            "Use verbs like define, identify, analyze, or apply."
          ],
          "Key Concepts and Explanations": [
            {{
              "Subtopic": "Concept name",
              "Explanation": "Provide a complete explanation of the concept — include definitions, examples, comparisons, and real-life applications."
            }},
            {{
              "Subtopic": "Another concept",
              "Explanation": "Explain it in the same depth."
            }}
          ],
          "Application or Examples": [
            "Write short applied scenarios or sample problems related to this topic."
          ],
          "Memory Tips": [
            "Include mnemonics, study tips, or simple ways to remember difficult parts."
          ],
          "Quick Recap": [
            "List the most important takeaways from this lesson."
          ]
        }}
        
        REFERENCE MATERIAL:
        \"\"\"{kb_text}\"\"\"
        
        Be very detailed and instructional — write like a teacher creating a study handout.
        If the reference material is short, elaborate with related fundamental concepts from the same academic domain.
        Ensure each field in your JSON contains full paragraph explanations, not just brief notes.
        Ensure your JSON is valid — escape quotes inside text and use commas correctly.
        Each section should have 3–5 sentences minimum.
        """

        completion = bedrock_llm.invoke_model(
            modelId=config['bedrock']['model_id'],  # amazon.nova-pro-v1:0
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]}
                ],
                "inferenceConfig": {
                    "maxTokens": maxTokens,
                    "temperature": 0.4,
                    "topP": 0.9
                }
            })
        )

        # --- Step 3: Parse the output (Nova Pro format) ---
        result = json.loads(completion["body"].read().decode("utf-8"))
        text_response = result["output"]["message"]["content"][0]["text"]

        # --- Step 4: Clean and safely parse JSON ---
        match = re.search(r"\{.*\}", text_response, re.S)
        if not match:
            # print("⚠️ Model did not return valid JSON:", text_response)
            return kb_text

        cleaned_json = match.group(0)
        try:
            outline_data = json.loads(cleaned_json)
        except json.JSONDecodeError as je:
            # print("⚠️ JSON decode failed, attempting auto-fix:", je)
            repaired = cleaned_json
            # Fix common issues
            repaired = re.sub(r"(\w)\"(\w)", r"\1'\"\2", repaired)  # stray quotes
            repaired = re.sub(r"\\(?![\"\\/bfnrtu])", r"\\\\", repaired)  # bad backslashes
            try:
                outline_data = json.loads(repaired)
            except Exception as inner_e:
                # print("⚠️ Still invalid JSON, returning raw output:", inner_e)
                return f"{kb_text}\n\n⚠️ Reviewer JSON parse failed — raw output:\n{text_response}"

        # --- Step 5: Combine into final reviewer text ---
        outline_section = "\n\n📘 Reviewer Lesson:\n"

        if outline_data.get("Lesson Overview"):
            outline_section += f"\nLesson Overview:\n{outline_data['Lesson Overview']}\n"

        if outline_data.get("Learning Objectives"):
            outline_section += "\nLearning Objectives:\n" + "\n".join(f"- {obj}" for obj in outline_data["Learning Objectives"])

        if outline_data.get("Key Concepts and Explanations"):
            outline_section += "\n\nKey Concepts and Explanations:\n"
            for item in outline_data["Key Concepts and Explanations"]:
                outline_section += f"\n🔹 {item['Subtopic']}:\n{item['Explanation']}\n"

        if outline_data.get("Application or Examples"):
            outline_section += "\nApplication or Examples:\n" + "\n".join(f"- {ex}" for ex in outline_data["Application or Examples"])

        if outline_data.get("Memory Tips"):
            outline_section += "\nMemory Tips:\n" + "\n".join(f"- {tip}" for tip in outline_data["Memory Tips"])

        if outline_data.get("Quick Recap"):
            outline_section += "\nQuick Recap:\n" + "\n".join(f"- {tip}" for tip in outline_data["Quick Recap"])

        # --- Step 6: Return final text ---
        if mode == "plain":
            return f"{kb_text}\n\n{outline_section}".strip()
        else:
            return f"Hey there! 😎 Let's go over your topic together!\n\n{kb_text}\n\n{outline_section}".strip()

    except Exception as e:
        # print("❌ Internal error in get_outline_and_notes:", str(e))
        # print(traceback.format_exc())
        return (
            "Hmm, something went wrong while generating your reviewer 😅 "
            "Please try again or check if the topic file was uploaded correctly."
        )