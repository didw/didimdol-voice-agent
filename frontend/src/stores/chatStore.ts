// frontend/src/stores/chatStore.ts
import { defineStore } from "pinia";
import { v4 as uuidv4 } from "uuid";
import { useSlotFillingStore } from "./slotFillingStore";
import type { SlotFillingUpdate } from "@/types/slotFilling";
import type { StageResponseMessage } from "@/types/stageResponse";

interface Message {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: Date;
  isStreaming?: boolean;
  isInterimStt?: boolean;
  stageResponse?: StageResponseMessage;
}

interface AudioSegment {
  // Represents audio for one sentence
  id: string;
  audioChunks: string[]; // base64 encoded MP3 chunks
}

interface ChatState {
  sessionId: string | null;
  messages: Message[];
  isProcessingLLM: boolean;
  isSynthesizingTTS: boolean;
  currentStageResponse: StageResponseMessage | null;

  ttsAudioSegmentQueue: AudioSegment[];
  _incomingTTSChunksForSentence: string[];

  error: string | null;
  currentInterimStt: string;
  isWebSocketConnected: boolean;
  webSocket: WebSocket | null;

  isVoiceModeActive: boolean;
  isRecording: boolean;
  audioContext: AudioContext | null;
  // --- 변경점: ScriptProcessorNode를 AudioWorkletNode로 교체 ---
  audioWorkletNode: AudioWorkletNode | null;
  audioStream: MediaStream | null;

  isPlayingTTS: boolean;
  _ttsAudioPlayer: HTMLAudioElement | null;

  isEPDDetectedByServer: boolean;

  vadContext: {
    audioContext: AudioContext | null;
    analyserNode: AnalyserNode | null;
    mediaStreamSource: MediaStreamAudioSourceNode | null; // VAD용 오디오 소스
    dataArray: Uint8Array | null;
    vadIntervalId: number | null;
    vadActivationTimeoutId: number | null;
  };
}

const WEBSOCKET_URL_BASE =
  import.meta.env.VITE_WEBSOCKET_URL ||
  "wss://aibranch.zapto.org/api/v1/chat/ws/";

export const useChatStore = defineStore("chat", {
  state: (): ChatState => ({
    sessionId: null,
    messages: [],
    isProcessingLLM: false,
    isSynthesizingTTS: false,
    currentStageResponse: null,

    ttsAudioSegmentQueue: [],
    _incomingTTSChunksForSentence: [],

    error: null,
    currentInterimStt: "",
    isWebSocketConnected: false,
    webSocket: null,

    isVoiceModeActive: false,
    isRecording: false,
    audioContext: null,
    // --- 변경점: 초기 상태값 변경 ---
    audioWorkletNode: null,
    audioStream: null,

    isPlayingTTS: false,
    _ttsAudioPlayer: null,
    isEPDDetectedByServer: false,

    vadContext: {
      audioContext: null,
      analyserNode: null,
      mediaStreamSource: null,
      dataArray: null,
      vadIntervalId: null,
      vadActivationTimeoutId: null,
    },
  }),
  actions: {
    _initializeAudioPlayer() {
      if (this._ttsAudioPlayer) return; // Run only once

      console.log("Initializing and unlocking shared TTS audio player.");
      this._ttsAudioPlayer = new Audio();

      // A tiny base64-encoded silent audio file.
      // Playing this during a user gesture "unlocks" the AudioContext for most browsers.
      this._ttsAudioPlayer.src =
        "data:audio/mp3;base64,SUQzBAAAAAABEVRYWFgAAAAtAAADY29tbWVudABCaXRyYXRlIHN1YnNpZHUgbGFtZSAzLjEwMAAAAAAAAAAAAAAA//OEAAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAAEAAABIADAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV6urq6urq6urq6urq6urq6urq6urq6urq6v////////////////////////////////8AAAAATGFtZTMuMTAwAAAAAAAAAAAAAAD/4xAmjAAAFaZhAMdxAAAKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq/s/4/4+VMy4w";

      // This play() call is critical. It must be initiated by a user gesture.
      this._ttsAudioPlayer.play().catch((e) => {
        console.warn(
          "Audio player could not be 'unlocked'. TTS might not play automatically.",
          e
        );
      });
    },
    initializeSessionAndConnect() {
      if (!this.sessionId) {
        this.sessionId = uuidv4();
        console.log("New session initialized:", this.sessionId);
      }
      if (!this.webSocket || this.webSocket.readyState === WebSocket.CLOSED) {
        this.connectWebSocket();
      } else if (this.webSocket.readyState === WebSocket.OPEN) {
        console.log("WebSocket already connected.");
      }
    },

    connectWebSocket() {
      if (!this.sessionId) {
        console.error("Session ID is not set. Cannot connect WebSocket.");
        this.error = "세션 ID가 없어 연결할 수 없습니다.";
        return;
      }
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        console.log("WebSocket is already connected.");
        return;
      }

      const fullWebSocketUrl = `${WEBSOCKET_URL_BASE}${this.sessionId}`;
      console.log("Attempting to connect WebSocket to:", fullWebSocketUrl);
      this.webSocket = new WebSocket(fullWebSocketUrl);

      this.webSocket.onopen = () => {
        console.log(
          "ONOPEN: WebSocket connection established for session:",
          this.sessionId
        );
        this.isWebSocketConnected = true;
        this.error = null;
        
        // 세션 초기화 시 슬롯 필링 상태도 초기화
        const slotFillingStore = useSlotFillingStore();
        slotFillingStore.clearSlotFilling();
      };

      this.webSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string);
          switch (data.type) {
            case "session_initialized":
              this.addMessage("ai", data.message);
              break;
            case "stt_interim_result":
              if (this.isVoiceModeActive) {
                this.currentInterimStt = data.transcript;
              }
              break;
            case "stt_final_result":
              this.currentInterimStt = "";
              if (data.transcript) {
                this.addMessage("user", data.transcript);
                this.isProcessingLLM = true;
              }
              break;
            case "llm_response_chunk":
              this.appendAiMessageChunk(data.chunk);
              this.isProcessingLLM = true;
              break;
            case "llm_response_end":
              this.finalizeAiMessage();
              this.isProcessingLLM = false;
              break;
            case "tts_audio_chunk":
              this._incomingTTSChunksForSentence.push(data.audio_chunk_base64);
              break;
            case "tts_stream_end":
              if (this._incomingTTSChunksForSentence.length > 0) {
                this.ttsAudioSegmentQueue.push({
                  id: uuidv4(),
                  audioChunks: [...this._incomingTTSChunksForSentence],
                });
                this._incomingTTSChunksForSentence = [];
              }
              this.playNextQueuedAudioSegment();
              break;
            case "epd_detected":
              console.log(
                "EPD detected by server (Google STT for previous user utterance)"
              );
              this.isEPDDetectedByServer = true;
              if (this.isPlayingTTS && this.isVoiceModeActive) {
                console.log(
                  "Server EPD received while AI TTS playing in voice mode. Client-side VAD handles barge-in."
                );
              } else if (this.isPlayingTTS && !this.isVoiceModeActive) {
                console.log(
                  "Server EPD received while AI TTS playing (NOT in voice mode). Stopping client TTS playback locally."
                );
                this.stopClientSideTTSPlayback(false);
              }
              break;
            case "voice_activated":
              console.log("Voice mode activated by server confirmation.");
              break;
            case "voice_deactivated":
              console.log("Voice mode deactivated by server confirmation.");
              this.isVoiceModeActive = false;
              this.stopRecording();
              break;
            case "slot_filling_update":
              try {
                const slotFillingStore = useSlotFillingStore();
                
                // DEBUG: 수신한 데이터 상세 로그
                console.log("===== SLOT FILLING UPDATE RECEIVED =====");
                console.log("Raw data:", data);
                console.log("Product Type:", data.productType);
                console.log("Required Fields Count:", data.requiredFields?.length || 0);
                console.log("Collected Info Count:", Object.keys(data.collectedInfo || {}).length);
                console.log("Completion Rate:", data.completionRate);
                console.log("Field Groups Count:", data.fieldGroups?.length || 0);
                
                // 필드별 상세 정보
                if (data.requiredFields) {
                  data.requiredFields.forEach((field: any) => {
                    const value = data.collectedInfo?.[field.key] || 'NOT_SET';
                    const completed = data.completionStatus?.[field.key] || false;
                    console.log(`Field '${field.key}': ${value} (completed: ${completed})`);
                  });
                }
                
                console.log("Full received data:", JSON.stringify(data, null, 2));
                console.log("===== END SLOT FILLING DEBUG =====");
                
                slotFillingStore.updateSlotFilling(data as SlotFillingUpdate);
                console.log("Slot filling update processed successfully");
              } catch (error) {
                console.error("Error processing slot filling update:", error);
                this.error = "정보 수집 상태 업데이트 중 오류가 발생했습니다.";
              }
              break;
            case "debug_slot_filling":
              console.log("===== DEBUG SLOT FILLING MESSAGE =====");
              console.log("Debug message received:", data);
              console.log("Data hash:", data.data_hash);
              console.log("Summary:", data.summary);
              console.log("===== END DEBUG MESSAGE =====");
              break;
            case "error":
              this.error = data.message;
              this.isProcessingLLM = false;
              this.isPlayingTTS = false;
              this._incomingTTSChunksForSentence = [];
              this.ttsAudioSegmentQueue = [];
              this.currentInterimStt = "";
              break;
            case "warning":
              this.addMessage("ai", `경고: ${data.message}`);
              break;
            case "stage_response":
              // Stage response를 현재 상태에 저장하고 메시지로도 추가
              this.currentStageResponse = {
                type: 'stage_response',
                stageId: data.stageId,
                responseType: data.responseType,
                prompt: data.prompt,
                choices: data.choices,
                skippable: data.skippable || false,
                modifiableFields: data.modifiableFields
              };
              
              // AI 메시지로 추가 (StageResponse 컴포넌트가 렌더링하도록)
              this.messages.push({
                id: uuidv4(),
                sender: 'ai',
                text: '', // 텍스트는 비워두고 stageResponse가 렌더링하도록
                timestamp: new Date(),
                isStreaming: false,
                stageResponse: this.currentStageResponse
              });
              
              // LLM 처리 완료 상태로 설정
              this.isProcessingLLM = false;
              break;
            default:
              console.warn("Unknown WebSocket message type:", data.type);
          }
        } catch (e) {
          console.error("Error parsing WebSocket message or in handler:", e);
          this.error = "서버로부터 잘못된 형식의 메시지를 받았습니다.";
        }
      };
      this.webSocket.onerror = (errorEvent) => {
        console.error("ONERROR: WebSocket error. Event:", errorEvent);
        this.error = "WebSocket 연결 중 오류가 발생했습니다.";
        this.isWebSocketConnected = false;
        this.isProcessingLLM = false;
        this.isPlayingTTS = false;
        this.isVoiceModeActive = false;
        this.stopRecording();
      };
      this.webSocket.onclose = (closeEvent) => {
        console.log(
          "ONCLOSE: WebSocket connection closed. Code:",
          closeEvent.code,
          "Reason:",
          closeEvent.reason,
          "WasClean:",
          closeEvent.wasClean
        );
        this.isWebSocketConnected = false;
        this.isProcessingLLM = false;
        this.isPlayingTTS = false;
        if (!closeEvent.wasClean) {
          this.error =
            "WebSocket 연결이 예상치 않게 종료되었습니다. (Code: " +
            closeEvent.code +
            ")";
        }
        this.isVoiceModeActive = false;
        this.stopRecording();
      };
    },

    async toggleVoiceMode() {
      if (
        !this.isWebSocketConnected ||
        (this.webSocket && this.webSocket.readyState !== WebSocket.OPEN)
      ) {
        this.initializeSessionAndConnect();
        await new Promise((resolve) => {
          const interval = setInterval(() => {
            if (this.isWebSocketConnected) {
              clearInterval(interval);
              resolve(true);
            }
          }, 100);
          setTimeout(() => {
            clearInterval(interval);
            if (!this.isWebSocketConnected) resolve(false);
          }, 3000);
        });
      }

      if (!this.isWebSocketConnected) {
        this.error = "서버 연결 실패. 음성 인식을 시작할 수 없습니다.";
        console.error(this.error);
        return;
      }
      this._initializeAudioPlayer();

      if (this.isVoiceModeActive) {
        await this.deactivateVoiceRecognition();
      } else {
        await this.activateVoiceRecognition();
      }
    },

    async activateVoiceRecognition() {
      if (
        !this.isWebSocketConnected ||
        !this.webSocket ||
        this.webSocket.readyState !== WebSocket.OPEN
      ) {
        this.error = "음성 인식을 시작하려면 서버에 연결되어 있어야 합니다.";
        return;
      }
      if (this.isPlayingTTS) {
        console.log(
          "Activating voice recognition, stopping current TTS playback."
        );
        this.stopClientSideTTSPlayback(true);
      }
      this.isVoiceModeActive = true;
      this.webSocket.send(JSON.stringify({ type: "activate_voice" }));
      await this.startRecording();
      this.currentInterimStt = "듣고 있어요...";
      this.error = null;
    },

    async deactivateVoiceRecognition() {
      await this.stopRecording();
      if (
        this.webSocket &&
        this.webSocket.readyState === WebSocket.OPEN &&
        this.isVoiceModeActive
      ) {
        this.webSocket.send(JSON.stringify({ type: "deactivate_voice" }));
      }
      this.isVoiceModeActive = false;
      this.currentInterimStt = "";
      this.isEPDDetectedByServer = false;
      this.stopClientSideVAD();
    },

    async startRecording() {
      if (this.isRecording || !this.isVoiceModeActive) return;

      try {
        const constraints = {
          audio: { echoCancellation: true, noiseSuppression: true },
        };
        this.audioStream = await navigator.mediaDevices.getUserMedia(
          constraints
        );

        if (this.isPlayingTTS) {
          console.log(
            "사용자 녹음 시작 중 TTS 재생 감지. Barge-in을 위해 TTS 중단."
          );
          this.stopClientSideTTSPlayback(true);
        }

        // --- Unified AudioContext setup ---
        // A single AudioContext will be used for both VAD and the AudioWorklet.
        // It's created if it doesn't exist or has been closed.
        if (!this.audioContext || this.audioContext.state === "closed") {
          this.audioContext = new (window.AudioContext ||
            (window as any).webkitAudioContext)();
        }

        // Create a single source node from the microphone stream.
        const source = this.audioContext.createMediaStreamSource(
          this.audioStream
        );

        // --- VAD setup ---
        // Create and connect the AnalyserNode for VAD.
        this.vadContext.analyserNode = this.audioContext.createAnalyser();
        this.vadContext.analyserNode.fftSize = 512;
        this.vadContext.analyserNode.smoothingTimeConstant = 0.5;
        this.vadContext.dataArray = new Uint8Array(
          this.vadContext.analyserNode.frequencyBinCount
        );
        source.connect(this.vadContext.analyserNode);
        console.log("VAD analyser connected to the unified audio graph.");

        // --- AudioWorklet setup ---
        await this.audioContext.audioWorklet.addModule("/audio-processor.js");
        this.audioWorkletNode = new AudioWorkletNode(
          this.audioContext,
          "audio-processor"
        );

        this.audioWorkletNode.port.onmessage = (event) => {
          if (!this.isRecording) return;
          const audioChunk = event.data as ArrayBuffer;
          if (
            audioChunk.byteLength > 0 &&
            this.isWebSocketConnected &&
            this.isVoiceModeActive
          ) {
            this.sendAudioChunk(audioChunk);
          }
        };

        this.audioWorkletNode.port.onmessageerror = (error) => {
          console.error("Error receiving message from AudioWorklet:", error);
        };

        // Connect the same source to the worklet. The output of 'source' fans out.
        source.connect(this.audioWorkletNode);
        console.log("AudioWorklet connected to the unified audio graph.");

        this.isRecording = true;
        console.log("Recording started using a unified AudioContext.");
      } catch (err) {
        console.error(
          "Error starting recording or setting up AudioWorklet:",
          err
        );
        this.error = "마이크 접근 또는 오디오 처리 모듈 설정에 실패했습니다.";
        if (this.isVoiceModeActive) this.isVoiceModeActive = false;
        await this.stopRecording(); // Cleanup on failure
      }
    },

    async stopRecording() {
      // Only proceed if there's something to stop.
      if (!this.isRecording && !this.audioContext) return;

      this.isRecording = false;

      // Stop the VAD check loops.
      this.stopClientSideVAD();

      // Stop the microphone stream tracks. This is the first step to release the hardware.
      if (this.audioStream) {
        this.audioStream.getTracks().forEach((track) => track.stop());
        this.audioStream = null;
      }

      // Disconnect the audio graph nodes.
      if (this.audioWorkletNode) {
        this.audioWorkletNode.port.close();
        this.audioWorkletNode.disconnect();
        this.audioWorkletNode = null;
      }
      if (this.vadContext.analyserNode) {
        this.vadContext.analyserNode.disconnect();
        this.vadContext.analyserNode = null;
        this.vadContext.dataArray = null;
      }

      // Close the main AudioContext, which releases all associated resources.
      if (this.audioContext && this.audioContext.state !== "closed") {
        await this.audioContext.close();
        this.audioContext = null;
      }

      // Ensure VAD context's own (now unused) context property is cleared.
      this.vadContext.audioContext = null;

      console.log("Recording stopped and all audio resources released.");
    },

    sendAudioChunk(audioChunk: ArrayBuffer) {
      if (
        this.webSocket &&
        this.webSocket.readyState === WebSocket.OPEN &&
        this.isVoiceModeActive
      ) {
        this.webSocket.send(audioChunk);
        this.error = null;
      } else if (!this.isVoiceModeActive) {
        // console.log("Audio chunk not sent: Voice mode is not active.");
      } else {
        this.handleWebSocketNotConnected("오디오 데이터");
      }
    },

    sendWebSocketTextMessage(text: string) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        if (this.isVoiceModeActive) {
          this.deactivateVoiceRecognition();
        }
        if (this.isPlayingTTS) {
          this.stopClientSideTTSPlayback(true);
        }
        this._initializeAudioPlayer(); // <--- 이 줄을 추가해주세요
        this.addMessage("user", text);
        this.webSocket.send(
          JSON.stringify({
            type: "process_text",
            text: text,
            input_mode: "text",
          })
        );
        this.isProcessingLLM = true;
        this.error = null;
      } else {
        this.handleWebSocketNotConnected("텍스트 메시지");
      }
    },

    sendAudioBlob(audioBlob: Blob) {
      if (
        this.webSocket &&
        this.webSocket.readyState === WebSocket.OPEN &&
        this.isVoiceModeActive
      ) {
        this.webSocket.send(audioBlob);
        this.error = null;
      } else if (!this.isVoiceModeActive) {
        // console.log("Audio blob not sent: Voice mode is not active.");
      } else {
        this.handleWebSocketNotConnected("오디오 데이터");
      }
    },

    stopClientSideTTSPlayback(notifyServer: boolean) {
      console.log(
        `Client attempting to stop TTS. Notify server: ${notifyServer}. Currently playing: ${this.isPlayingTTS}`
      );

      const audioPlayer = this._ttsAudioPlayer;
      if (audioPlayer) {
        // Setting handlers to null prevents the 'onended' of the interrupted track
        // from triggering playback of the next track in the old queue.
        audioPlayer.onended = null;
        audioPlayer.onerror = null;

        if (!audioPlayer.paused) {
          audioPlayer.pause();
        }

        // Revoke the URL of the audio we just stopped to prevent memory leaks.
        if (audioPlayer.src && audioPlayer.src.startsWith("blob:")) {
          URL.revokeObjectURL(audioPlayer.src);
        }

        // 중요: .src 를 '' 로 만들거나 .load()를 호출하지 않습니다.
        // 이것이 플레이어의 '잠금 해제' 상태를 보존하는 핵심입니다.
      }

      // 이전 오디오가 재생되지 않도록 큐를 비웁니다.
      this.ttsAudioSegmentQueue = [];
      this._incomingTTSChunksForSentence = [];

      this.isPlayingTTS = false;

      // TTS가 더 이상 재생되지 않으므로 VAD 모니터링을 중지합니다.
      this.stopClientSideVAD();

      if (
        notifyServer &&
        this.webSocket &&
        this.webSocket.readyState === WebSocket.OPEN
      ) {
        this.webSocket.send(JSON.stringify({ type: "stop_tts" }));
        console.log("Sent stop_tts to server.");
      }
    },

    playNextQueuedAudioSegment() {
      if (
        this.isPlayingTTS ||
        this.ttsAudioSegmentQueue.length === 0 ||
        !this._ttsAudioPlayer
      ) {
        if (this.ttsAudioSegmentQueue.length === 0 && !this.isPlayingTTS) {
          console.log("All TTS audio segments have been played.");
        }
        if (!this._ttsAudioPlayer) {
          console.warn("TTS player not initialized. Cannot play audio.");
        }
        return;
      }

      const segmentToPlay = this.ttsAudioSegmentQueue.shift();
      if (!segmentToPlay || segmentToPlay.audioChunks.length === 0) {
        this.playNextQueuedAudioSegment(); // Play next if current is empty
        return;
      }

      this.isPlayingTTS = true;
      console.log(
        `Playback starting for audio segment (ID: ${segmentToPlay.id}) with ${segmentToPlay.audioChunks.length} combined chunks.`
      );

      try {
        const decodedChunks = segmentToPlay.audioChunks.map((chunk) => {
          const binaryString = window.atob(chunk);
          const len = binaryString.length;
          const bytes = new Uint8Array(len);
          for (let i = 0; i < len; i++) {
            bytes[i] = binaryString.charCodeAt(i);
          }
          return bytes;
        });

        const audioBlob = new Blob(decodedChunks, { type: "audio/mp3" });
        const audioUrl = URL.createObjectURL(audioBlob);

        const audioPlayer = this._ttsAudioPlayer; // Use the shared player

        const cleanupAndPlayNext = () => {
          this.isPlayingTTS = false;
          URL.revokeObjectURL(audioUrl); // Clean up blob URL
          if (audioPlayer) {
            audioPlayer.onended = null;
            audioPlayer.onerror = null;
          }
          this.playNextQueuedAudioSegment();
        };

        audioPlayer.onended = () => {
          console.log(
            `Playback finished for audio segment (ID: ${segmentToPlay.id})`
          );
          cleanupAndPlayNext();
        };

        audioPlayer.onerror = (e) => {
          console.error("Error during TTS audio element playback:", e);
          this.error = "TTS 오디오 재생 중 오류가 발생했습니다.";
          cleanupAndPlayNext();
        };

        audioPlayer.src = audioUrl;
        audioPlayer.play().catch((error) => {
          console.error("Error programmatically playing TTS audio:", error);
          this.error = "TTS 오디오를 재생할 수 없습니다.";
          cleanupAndPlayNext();
        });

        if (this.isVoiceModeActive) {
          this.startClientSideVAD();
        }
      } catch (e) {
        console.error("Failed to decode or play TTS audio:", e);
        this.error = "TTS 오디오 데이터를 처리하는 중 오류가 발생했습니다.";
        this.isPlayingTTS = false;
        this.playNextQueuedAudioSegment();
      }
    },

    startClientSideVAD() {
      this.stopClientSideVAD(); // 이전 인터벌 정리

      if (
        !this.isVoiceModeActive ||
        !this.isPlayingTTS ||
        !this.vadContext.analyserNode
      ) {
        return;
      }

      this.vadContext.vadActivationTimeoutId = window.setTimeout(() => {
        if (
          !this.isVoiceModeActive ||
          !this.isPlayingTTS ||
          !this.vadContext.analyserNode
        ) {
          this.stopClientSideVAD();
          return;
        }

        const VAD_THRESHOLD = 20;
        const SPEECH_FRAMES_NEEDED_FOR_BARGE_IN = 4;
        let consecutiveSpeechFrames = 0;

        this.vadContext.vadIntervalId = window.setInterval(() => {
          if (
            !this.vadContext.analyserNode ||
            !this.vadContext.dataArray ||
            !this.isPlayingTTS ||
            !this.isVoiceModeActive
          ) {
            this.stopClientSideVAD();
            return;
          }
          this.vadContext.analyserNode.getByteFrequencyData(
            this.vadContext.dataArray
          );
          let sum = 0;
          for (let i = 0; i < this.vadContext.dataArray.length; i++) {
            sum += this.vadContext.dataArray[i];
          }
          const average =
            this.vadContext.dataArray.length > 0
              ? sum / this.vadContext.dataArray.length
              : 0;

          if (average > VAD_THRESHOLD) {
            consecutiveSpeechFrames++;
            if (consecutiveSpeechFrames >= SPEECH_FRAMES_NEEDED_FOR_BARGE_IN) {
              console.log(
                `Client VAD: User speaking detected (avg: ${average.toFixed(
                  2
                )}). Stopping TTS for barge-in.`
              );
              this.stopClientSideTTSPlayback(true);
            }
          } else {
            consecutiveSpeechFrames = 0;
          }
        }, 100);
      }, 300);
    },

    stopClientSideVAD() {
      if (this.vadContext.vadActivationTimeoutId) {
        clearTimeout(this.vadContext.vadActivationTimeoutId);
        this.vadContext.vadActivationTimeoutId = null;
      }
      if (this.vadContext.vadIntervalId) {
        clearInterval(this.vadContext.vadIntervalId);
        this.vadContext.vadIntervalId = null;
      }
    },

    handleWebSocketNotConnected(actionDescription: string) {
      console.error(
        `Cannot send ${actionDescription}: WebSocket is not connected.`
      );
      this.error = `서버와 연결되지 않아 ${actionDescription}을 전송할 수 없습니다. 페이지를 새로고침하거나 잠시 후 다시 시도해주세요.`;
    },
    addMessage(sender: "user" | "ai", text: string) {
      const newMessage: Message = {
        id: uuidv4(),
        sender,
        text,
        timestamp: new Date(),
        isStreaming: false,
        isInterimStt: false,
      };
      this.messages.push(newMessage);
    },
    appendAiMessageChunk(chunk: string) {
      const lastMessage = this.messages[this.messages.length - 1];
      if (
        lastMessage &&
        lastMessage.sender === "ai" &&
        lastMessage.isStreaming
      ) {
        lastMessage.text += chunk;
      } else {
        this.finalizeAiMessage();
        this.messages.push({
          id: uuidv4(),
          sender: "ai",
          text: chunk,
          timestamp: new Date(),
          isStreaming: true,
        });
      }
    },
    finalizeAiMessage() {
      const lastMessage = this.messages[this.messages.length - 1];
      if (
        lastMessage &&
        lastMessage.sender === "ai" &&
        lastMessage.isStreaming
      ) {
        lastMessage.isStreaming = false;
      }
    },
    
    // Stage Response 관련 메서드들
    sendUserChoice(stageId: string, selectedChoice: string) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(
          JSON.stringify({
            type: "user_choice_selection",
            stageId: stageId,
            selectedChoice: selectedChoice,
          })
        );
        // Add user message to show the selection
        this.addMessage("user", selectedChoice);
        this.isProcessingLLM = true;
      }
    },
    
    sendBooleanSelections(stageId: string, selections: Record<string, boolean>) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(
          JSON.stringify({
            type: "user_boolean_selection",
            stageId: stageId,
            booleanSelections: selections,
          })
        );
        // 키를 한글로 변환하는 매핑
        const keyTranslations: Record<string, string> = {
          important_transaction_alert: "중요거래 알림",
          withdrawal_alert: "출금내역 알림", 
          overseas_ip_restriction: "해외IP 제한"
        };
        
        // Format selections for display with Korean labels
        const displayText = Object.entries(selections)
          .map(([key, value]) => {
            const koreanLabel = keyTranslations[key] || key;
            return `${koreanLabel}: ${value ? "신청" : "미신청"}`;
          })
          .join(", ");
        this.addMessage("user", displayText);
        this.isProcessingLLM = true;
      }
    },
    
    sendModificationRequest(field: string, newValue: any) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(
          JSON.stringify({
            type: "user_modification_request",
            field: field,
            newValue: newValue,
          })
        );
        this.addMessage("user", `${field} 수정: ${newValue}`);
        this.isProcessingLLM = true;
      }
    },
    
    disconnectWebSocket() {
      if (this.isVoiceModeActive) {
        this.deactivateVoiceRecognition();
      }
      this.stopClientSideTTSPlayback(false);
      if (this.webSocket) {
        this.webSocket.onopen = null;
        this.webSocket.onmessage = null;
        this.webSocket.onerror = null;
        this.webSocket.onclose = null;
        if (
          this.webSocket.readyState === WebSocket.OPEN ||
          this.webSocket.readyState === WebSocket.CONNECTING
        ) {
          this.webSocket.close(1000, "Client initiated disconnect");
        }
        this.webSocket = null;
      }
      this.isWebSocketConnected = false;
      console.log("WebSocket disconnected by client action.");
    },
  },
  getters: {
    getMessages: (state): Message[] => state.messages,
    getIsProcessingLLM: (state): boolean => state.isProcessingLLM,
    getIsPlayingTTS: (state): boolean => state.isPlayingTTS,
    getError: (state): string | null => state.error,
    getSessionId: (state): string | null => state.sessionId,
    getInterimStt: (state): string => state.currentInterimStt,
    getIsWebSocketConnected: (state): boolean => state.isWebSocketConnected,
    getIsVoiceModeActive: (state): boolean => state.isVoiceModeActive,
    getIsRecording: (state): boolean => state.isRecording,
    getIsEPDDetectedByServer: (state): boolean => state.isEPDDetectedByServer,
    getIsSynthesizingTTS: (state) => state.isSynthesizingTTS,
    getCurrentStageResponse: (state): StageResponseMessage | null => state.currentStageResponse,
  },
});
