import axios from 'axios'
import type { AxiosInstance } from 'axios'

interface ProcessMessagePayload {
  session_id: string
  text?: string
  audio_bytes_str?: string
}

interface ApiResponse {
  data: {
    text: string
    tts_audio_base64?: string
    debug_info?: {
      tts_audio_base64?: string
    }
  }
}

interface ReloadScenarioRequest {
  product_type?: string
}

interface ReloadScenarioResponse {
  success: boolean
  message: string
  product_type?: string
}

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

export default {
  processMessage(payload: ProcessMessagePayload): Promise<ApiResponse> {
    return apiClient.post('/chat/process_message', payload)
  },

  streamTTS(text: string): Promise<Blob> {
    return apiClient.post(
      '/chat/stream_tts',
      { text },
      {
        responseType: 'blob',
      },
    )
  },

  reloadScenario(productType?: string): Promise<{ data: ReloadScenarioResponse }> {
    return apiClient.post('/chat/reload-scenario', {
      product_type: productType
    })
  },
}
