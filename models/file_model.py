class File:
    def __init__(self, **data):
        self.file_name = data.get('file_name')
        self.file_type = data.get('file_type')
        self.s3_file_name = data.get('s3_file_name')
        self.file_size = data.get('file_size')
