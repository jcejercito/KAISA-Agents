import os
import json
from datetime import datetime
from typing import ClassVar, Optional
from zoneinfo import ZoneInfo

from factories.dynamodb_factory import DynamodbFactory
from models.chat_model import Chat

class ChatRepository(DynamodbFactory(Chat)):
    DDB_TABLE_NAME: ClassVar[str | None] = None
    DDB_CLIENT: ClassVar = None
    WEBSOCKET_CLIENT: ClassVar = None
    model_class = Chat

    @classmethod
    def push_to_client(cls, connection_id: str, response: dict):
        """Send message to WebSocket client"""
        if not cls.WEBSOCKET_CLIENT or not connection_id:
            return
        
        try:
            cls.WEBSOCKET_CLIENT.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(response)
            )
        except Exception as e:
            print(f"Failed to send WebSocket message: {str(e)}")

    @classmethod
    def initialize_chat_user(
        cls,
        user_id: str,
        user_input: str,
        session_id: str,
        file_input: Optional = None,
    ) -> Chat:
        file_name = None
        file_type = None
        s3_file_name = None
        
        if file_input:
            file_name = file_input.file_name
            file_type = file_input.file_type
            s3_file_name = file_input.s3_file_name

        data = {
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now(
                ZoneInfo(os.getenv("TZ", "Asia/Manila").lstrip(":"))
            ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "role": "user",
            "message": user_input,
            "file_name": file_name,
            "s3_file_name": s3_file_name,
            "file_type": file_type,
        }

        Chat.REPOSITORY = cls
        model = Chat(**data)
        return model

    @classmethod
    def initialize_chat_agent(
        cls, user_id: str, agent_response: str, session_id: str
    ) -> Chat:
        data = {
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now(
                ZoneInfo(os.getenv("TZ", "Asia/Manila").lstrip(":"))
            ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "role": "assistant",
            "message": agent_response,
        }
        Chat.REPOSITORY = cls
        model = Chat(**data)
        return model

    @classmethod
    def compile_chat_history(
        cls,
        session_id: str,
        message_count: int | None = None,
        context_window: int = 8,
        model_id: str | None = None,
    ):

        chat_messages, _ = cls.query(
            table_name=cls.DDB_TABLE_NAME,
            hash_key=session_id,
            range_key_condition=None,
            scan_index_forward=False,
            limit=context_window * 2,
        )

        messages = []
        for old_message in reversed(chat_messages):
            content = [{"text": old_message.message}]
            messages.append({
                "role": old_message.role,
                "content": content,
            })

        return messages

    @classmethod
    def format_session_summary(cls, current_summary):
        if not current_summary:
            return []
        
        return [{
            "role": "user",
            "content": [{
                "text": f"Here is the current summary of the session: {current_summary}"
            }],
        }]

    @classmethod
    def save(cls, chat_object: Chat):
        return cls.write(
            table_name=cls.DDB_TABLE_NAME, 
            object_data=chat_object
        )
