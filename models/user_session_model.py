from typing import ClassVar

class UserSession:
    REPOSITORY: ClassVar
    
    def __init__(self, **data):
        self.user_id = data['user_id']
        self.timestamp = data['timestamp']
        self.session_id = data['session_id']
        self.title = data['title']
        self.session_summary = data.get('session_summary', '')
        self.is_deleted = data.get('is_deleted', False)
        self.has_ended = data.get('has_ended', False)
        self.message_count = data.get('message_count', 0)
        self.message_count_summarized = data.get('message_count_summarized', 0)
