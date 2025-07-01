Of course. Here is the revised content in a simplified format.

---

_This file provides guidance for AI assistants working with code in this repository._

## 1\. Project Overview

This project is the **"디딤돌 음성 상담 에이전트" (Didimdol Voice Consultation Agent)**, a voice-based AI demo for Korean financial loan consultations. It features real-time Speech-to-Text (STT) and Text-to-Speech (TTS).

- **Backend**: **Python**, **FastAPI**, and **LangGraph** for the core agent logic.
- **Frontend**: **Vue.js**, **Vite**, and **TypeScript** for the user interface.
- **Key Services**: **OpenAI** (LLM), **Google Cloud** (STT/TTS), **LanceDB** (RAG), and **Tavily** (Web Search).

---

## 2\. Key Commands

### Backend

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

### Full Stack

```bash
# Run both backend and frontend
./scripts/run_dev.sh
```

---

## 3\. Architecture

The system uses a client-server architecture with real-time communication.

- **Backend**: A stateful **LangGraph** agent built on **FastAPI**. It uses **WebSockets** to handle real-time audio and text streams. The agent routes user requests to internal knowledge (**RAG**), external knowledge (**Web Search**), or structured consultation **scenarios**.

- **Frontend**: A **Vue.js** single-page application. It uses the **Web Audio API** to capture microphone input and **Pinia** to manage application state, including the WebSocket connection.

---

## 4\. Environment & Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory with the following keys:

```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/google-credentials.json
```

### Configuration Files

Agent behavior and data are managed externally, not hardcoded.

- **Prompts**: Defined in `.yaml` files in `backend/app/config/`.
- **Knowledge Base**: Stored as `.md` files in `backend/app/data/`.
- **Scenarios**: Structured as `.json` files in `backend/app/data/`.

---

## 5\. Testing

- **Backend**: No automated test framework is configured. Test manually by running the server.
- **Frontend**: Unit tests are available and can be run with **Vitest**.
  ```bash
  npm run test:unit
  ```

---

## 6\. Module Documentation

For detailed module-specific guidance:

- [Backend CLAUDE.md](backend/CLAUDE.md) - Backend API and agent implementation
- [Frontend CLAUDE.md](frontend/CLAUDE.md) - Vue.js user interface
- [Nginx CLAUDE.md](nginx/CLAUDE.md) - Production deployment configuration
