_This file provides guidance for AI assistants working with the frontend code in this repository._

## Frontend Module - 디딤돌 음성 상담 에이전트

This is the **frontend** module of the 디딤돌 Voice Consultation Agent, providing the user interface for voice-based financial consultations.

### Role
- **Vue.js** single-page application with TypeScript
- **Real-time voice interaction** using Web Audio API
- **WebSocket communication** with backend agent
- **State management** with Pinia
- **Responsive UI** for consultation interface

### Key Commands
```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Run unit tests
npm run test:unit
```

### Architecture
- `src/main.ts` - Application entry point
- `src/App.vue` - Root component
- `src/components/` - Reusable Vue components
- `src/services/` - API communication layer
- `src/stores/` - Pinia state management
- `src/views/` - Page-level components
- `public/audio-processor.js` - Web Audio API processor

### Testing
Unit tests available with **Vitest**:
```bash
npm run test:unit
```

### Related Files
- [Root CLAUDE.md](../CLAUDE.md) - Main project overview
- [Backend CLAUDE.md](../backend/CLAUDE.md) - Backend module documentation