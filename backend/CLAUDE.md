_This file provides guidance for AI assistants working with the backend code in this repository._

## Backend Module - 디딤돌 음성 상담 에이전트

This is the **backend** module of the 디딤돌 Voice Consultation Agent, handling the core AI agent logic and API services.

### Role
- **FastAPI** server providing REST and WebSocket endpoints
- **LangGraph** agent for conversation flow and decision routing
- **RAG** (Retrieval Augmented Generation) for knowledge base queries
- **STT/TTS** integration with Google Cloud services
- **Web search** integration via Tavily

### Key Commands
```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --port 8000
```

### Architecture
- `app/main.py` - FastAPI application entry point
- `app/api/` - REST API endpoints
- `app/graph/` - LangGraph agent implementation
- `app/rag/` - RAG pipeline and vector search
- `app/services/` - External service integrations
- `app/config/` - Agent prompts and configurations
- `app/data/` - Knowledge base and scenario data

### Environment Setup
Create `.env` file with:
```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/google-credentials.json
```

### Related Files
- [Root CLAUDE.md](../CLAUDE.md) - Main project overview
- [Frontend CLAUDE.md](../frontend/CLAUDE.md) - Frontend module documentation