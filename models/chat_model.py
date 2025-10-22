from typing import ClassVar, Optional

class Chat:
    REPOSITORY: ClassVar
    
    def __init__(self, **data):
        self.session_id = data['session_id']
        self.timestamp = data['timestamp']
        self.role = data['role']
        self.message = data.get('message', '')
        self.user_id = data['user_id']
        self.file_name = data.get('file_name')
        self.s3_file_name = data.get('s3_file_name')
        self.file_type = data.get('file_type')
        self.topic = data.get('topic')
