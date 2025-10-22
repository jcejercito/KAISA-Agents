import boto3
from typing import ClassVar

def DynamodbFactory(model_cls):
    class _DynamodbFactory:
        DDB_CLIENT: ClassVar = None
        DDB_TABLE_NAME: ClassVar[str | None] = None

        @classmethod
        def write(cls, table_name: str, object_data):
            # Minimal DynamoDB write implementation
            item = {
                'PK': {'S': object_data.session_id if hasattr(object_data, 'session_id') else object_data.user_id},
                'SK': {'S': object_data.timestamp},
                'user_id': {'S': object_data.user_id},
                'message': {'S': getattr(object_data, 'message', '')},
                'role': {'S': getattr(object_data, 'role', '')},
            }
            
            # Add optional fields
            if hasattr(object_data, 'session_id'):
                item['session_id'] = {'S': object_data.session_id}
            if hasattr(object_data, 'file_name') and object_data.file_name:
                item['file_name'] = {'S': object_data.file_name}
            if hasattr(object_data, 's3_file_name') and object_data.s3_file_name:
                item['s3_file_name'] = {'S': object_data.s3_file_name}
            if hasattr(object_data, 'file_type') and object_data.file_type:
                item['file_type'] = {'S': object_data.file_type}
            if hasattr(object_data, 'title'):
                item['title'] = {'S': object_data.title}
            if hasattr(object_data, 'session_summary') and object_data.session_summary:
                item['session_summary'] = {'S': object_data.session_summary}
            if hasattr(object_data, 'message_count'):
                item['message_count'] = {'N': str(object_data.message_count)}
            if hasattr(object_data, 'is_deleted'):
                item['is_deleted'] = {'BOOL': object_data.is_deleted}
            if hasattr(object_data, 'has_ended'):
                item['has_ended'] = {'BOOL': object_data.has_ended}
            if hasattr(object_data, 'message_count_summarized'):
                item['message_count_summarized'] = {'N': str(object_data.message_count_summarized)}
                
            return cls.DDB_CLIENT.put_item(TableName=table_name, Item=item)

        @classmethod
        def query(cls, table_name: str, hash_key: str, range_key_condition=None, 
                  filter_condition=None, scan_index_forward=True, limit=None, **kwargs):
            # Minimal DynamoDB query implementation
            key_condition = f"PK = :pk"
            expression_values = {':pk': {'S': hash_key}}
            
            if range_key_condition:
                key_condition += f" AND SK = :sk"
                expression_values[':sk'] = {'S': range_key_condition['value']}
                
            query_params = {
                'TableName': table_name,
                'KeyConditionExpression': key_condition,
                'ExpressionAttributeValues': expression_values,
                'ScanIndexForward': scan_index_forward
            }
            
            if limit:
                query_params['Limit'] = limit
                
            response = cls.DDB_CLIENT.query(**query_params)
            
            # Convert DynamoDB items to model objects
            items = []
            for item in response.get('Items', []):
                data = {}
                for key, value in item.items():
                    if 'S' in value:
                        data[key] = value['S']
                    elif 'N' in value:
                        data[key] = int(value['N'])
                    elif 'BOOL' in value:
                        data[key] = value['BOOL']
                        
                # Map DynamoDB fields to model fields
                if 'PK' in data:
                    if 'session_id' in data:
                        data['session_id'] = data['PK']
                    else:
                        data['user_id'] = data['PK']
                if 'SK' in data:
                    data['timestamp'] = data['SK']
                    
                items.append(model_cls(**data))
                
            return items, response.get('LastEvaluatedKey')
    
    return _DynamodbFactory
