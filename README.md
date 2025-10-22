# KAISA-Agents

**K**nowledge **A**ugmented **I**ntelligent **S**mart **A**gents - A multi-agent AI system for K-12 education built on AWS infrastructure.

## Overview

KAISA-Agents is an intelligent educational platform that provides specialized AI agents to support K-12 learning. The system uses AWS Bedrock, DynamoDB, and WebSocket APIs to deliver real-time, context-aware educational assistance through multiple specialized agents.

## Architecture

The system follows a multi-agent architecture with the following components:

### Core Agents
- **General Agent** - Main coordinator and learning journey guide
- **Curriculum Agent** - Handles curriculum-specific queries and content retrieval
- **Quizzer Agent** - Creates and manages interactive quizzes and assessments
- **Review Agent** - Generates comprehensive study materials and PDF reviewers

### Infrastructure Components
- **AWS Lambda** - Serverless compute for agent execution
- **Amazon Bedrock** - AI/ML foundation models (Nova Pro v1)
- **DynamoDB** - Chat history and session management
- **S3** - File storage for generated content
- **API Gateway WebSocket** - Real-time communication
- **Knowledge Base** - Educational content retrieval

## Project Structure

```
KAISA-Agents/
├── agents/                     # AI agent implementations
│   ├── config/                # Agent configuration files
│   ├── utils/                 # Agent-specific utilities
│   ├── general_agent.py       # Main coordinator agent
│   ├── curriculum_agent.py    # Curriculum specialist
│   ├── quizzer_agent.py       # Quiz generation agent
│   └── review_agent.py        # Study material generator
├── handlers/                   # Lambda function handlers
│   └── main_handler.py        # Main request handler
├── repositories/               # Data access layer
│   ├── chat_repository.py     # Chat history management
│   └── user_session_repository.py # User session handling
├── models/                     # Data models
│   ├── chat_model.py          # Chat message structure
│   ├── file_model.py          # File metadata
│   └── user_session_model.py  # Session data
├── factories/                  # Factory patterns
│   └── dynamodb_factory.py    # DynamoDB operations
├── chat_context/              # Context management
│   └── context_manager.py     # Chat context building
└── utils/                     # Shared utilities
    └── chat_utils.py          # AWS client initialization
```

## Features

### Multi-Agent System
- **Intelligent Routing** - Automatically directs queries to appropriate specialized agents
- **Context Awareness** - Maintains conversation history and learning progress
- **Real-time Communication** - WebSocket-based streaming responses

### Educational Capabilities
- **Curriculum Support** - Aligned with K-12 educational standards
- **Interactive Quizzes** - Dynamic quiz generation and assessment
- **Study Materials** - PDF reviewer generation with DepEd formatting
- **Knowledge Retrieval** - Access to curated educational content

### Technical Features
- **Serverless Architecture** - Scalable AWS Lambda deployment
- **Guardrails** - Built-in content safety and appropriateness filters
- **Session Management** - Persistent user sessions and progress tracking
- **File Processing** - PDF parsing and content extraction

## Configuration

### Environment Variables

```bash
# AWS Configuration
AWS_REGION=us-east-1
BEDROCK_REGION=us-east-1
ACCESS_KEY=your_access_key
SECRET_KEY=your_secret_key

# Bedrock Settings
BEDROCK_CONNECT_TIMEOUT=5
BEDROCK_READ_TIMEOUT=120
BEDROCK_MAX_ATTEMPTS=2

# Database
CHAT_TABLE=your_dynamodb_table
KB_ID=your_knowledge_base_id

# WebSocket API
WEBSOCKET_API_ID=your_api_id
WEBSOCKET_STAGE=prod

# Context Settings
CONTEXT_WINDOW=8
```

### Agent Configuration

Each agent has its own configuration file in `agents/config/`:

```json
{
    "aws_region": "us-east-1",
    "bedrock": {
        "model_id": "amazon.nova-pro-v1:0",
        "guardrail_id": "0c3t6v38zujx",
        "guardrail_version": "1",
        "guardrail_trace": "enabled"
    }
}
```

## Dependencies

### Core Dependencies
- `boto3` - AWS SDK for Python
- `strands` - Agent framework and Bedrock model integration
- `PyMuPDF` (fitz) - PDF processing
- `reportlab` - PDF generation

### AWS Services
- Amazon Bedrock (Nova Pro v1)
- DynamoDB
- S3
- Lambda
- API Gateway
- Knowledge Bases for Amazon Bedrock

## Usage

### Agent Interaction

The system automatically routes requests to appropriate agents:

```python
# General queries go to General Agent
"Help me understand photosynthesis"

# Curriculum-specific queries go to Curriculum Agent  
"What are the Grade 7 science topics for Q2?"

# Quiz requests go to Quizzer Agent
"Create a quiz about fractions"

# Review material requests go to Review Agent
"Generate a reviewer for Philippine history"
```

### API Integration

The main handler processes requests and streams responses:

```python
from handlers.main_handler import get_agent, stream_to_client_and_persist

# Get appropriate agent
agent = get_agent("curriculum")

# Process request with streaming
await stream_to_client_and_persist(
    agent_module=agent,
    payload=request_data,
    connection_id=connection_id,
    domain=domain,
    stage=stage,
    session_id=session_id,
    user_id=user_id
)
```

## Deployment

### AWS Lambda Deployment

1. Package the application with dependencies
2. Configure environment variables
3. Set up DynamoDB tables
4. Configure API Gateway WebSocket API
5. Deploy Lambda function

### Required AWS Resources

- Lambda function with appropriate IAM roles
- DynamoDB table for chat history
- S3 bucket for file storage
- Bedrock model access permissions
- Knowledge Base setup
- WebSocket API configuration

## Development

### Local Development Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure AWS credentials
4. Set environment variables
5. Run tests and local development server

### Adding New Agents

1. Create agent file in `agents/` directory
2. Add configuration in `agents/config/`
3. Update `main_handler.py` routing
4. Implement required tools and methods
5. Test integration

## Security

- **Guardrails** - Content filtering and safety measures
- **IAM Roles** - Least privilege access principles
- **Environment Variables** - Secure credential management
- **Input Validation** - Request sanitization and validation

## Monitoring

- CloudWatch logs for debugging
- DynamoDB metrics for performance
- Bedrock usage tracking
- WebSocket connection monitoring

## Contributing

1. Follow Python coding standards
2. Add appropriate logging
3. Update documentation
4. Test thoroughly before deployment
5. Follow security best practices

## License

This project is part of the KAISA educational initiative for K-12 learning enhancement.