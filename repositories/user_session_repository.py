import os
import random
import string
from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

from factories.dynamodb_factory import DynamodbFactory
from models.user_session_model import UserSession

class UserSessionRepository(DynamodbFactory(UserSession)):
    DDB_TABLE_NAME: ClassVar[str | None] = None
    DDB_CLIENT: ClassVar = None
    model_class = UserSession

    @staticmethod
    def construct_session_id(user_id: str):
        random_part = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        session_id = f"{user_id}-{random_part}"
        return session_id

    @classmethod
    def initialize_user_session(
        cls, user_id: str, session_id: str, summary: str, title: str
    ):
        data = {
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now(
                ZoneInfo(os.getenv("TZ", "Asia/Manila").lstrip(":"))
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "session_summary": summary,
            "is_deleted": False,
            "has_ended": False,
            "message_count": 0,
            "message_count_summarized": 0,
        }
        UserSession.REPOSITORY = cls
        model = UserSession(**data)
        return model

    @classmethod
    def get_user_session(cls, user_id: str, session_id: str):
        session_details, _ = cls.query(
            table_name=cls.DDB_TABLE_NAME,
            hash_key=session_id,  # ✅ correct key — PK = session_id
            limit=1,
        )
        return session_details[0] if session_details else None

    @classmethod
    def save(cls, session_object: UserSession):
        return cls.write(
            table_name=cls.DDB_TABLE_NAME, 
            object_data=session_object
        )
