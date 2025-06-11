/**
 * 오디오 버퍼를 목표 샘플레이트로 리샘플링합니다.
 * @param {Float32Array} audioBuffer - 원본 Float32Array 오디오 데이터
 * @param {number} fromSampleRate - 원본 샘플레이트 (e.g., 44100)
 * @param {number} toSampleRate - 목표 샘플레이트 (e.g., 16000)
 * @returns {Float32Array} 리샘플링된 Float32Array 오디오 데이터
 */
function resampleBuffer(audioBuffer, fromSampleRate, toSampleRate) {
    if (fromSampleRate === toSampleRate) {
      return audioBuffer;
    }
    
    const sampleRateRatio = fromSampleRate / toSampleRate;
    const newLength = Math.round(audioBuffer.length / sampleRateRatio);
    const result = new Float32Array(newLength);
    
    let offsetResult = 0;
    let offsetBuffer = 0;
    
    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
      let accum = 0, count = 0;
      
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < audioBuffer.length; i++) {
        accum += audioBuffer[i];
        count++;
      }
      
      // count가 0인 경우(엣지 케이스)를 방지
      result[offsetResult] = count > 0 ? accum / count : 0;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }
    
    return result;
  }
  
  /**
   * Float32Array 형식의 PCM 오디오 데이터를 Int16Array 형식으로 변환합니다.
   * @param {Float32Array} buffer - Float32Array 형식의 오디오 데이터
   * @returns {ArrayBuffer} Int16Array 형식의 오디오 데이터 ArrayBuffer
   */
  function convertFloat32ToInt16(buffer) {
    let l = buffer.length;
    const buf = new Int16Array(l);
    while (l--) {
      // Float32 값(-1.0 ~ 1.0)을 Int16 값(-32768 ~ 32767)으로 변환
      buf[l] = Math.min(1, buffer[l]) * 0x7FFF;
    }
    return buf.buffer;
  }
  
  
  /**
   * AudioWorklet 환경에서 실행되는 커스텀 오디오 프로세서입니다.
   * 마이크 입력을 받아 리샘플링 및 포맷 변환 후 메인 스레드로 전송합니다.
   */
  class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
      super();
      this.targetSampleRate = 16000;
    }
  
    /**
     * 오디오 데이터 블록이 들어올 때마다 호출되는 메인 처리 함수입니다.
     * @param {Float32Array[][]} inputs - 입력 채널의 배열. inputs[0]이 첫 번째 입력.
     * @param {Float32Array[][]} outputs - 출력 채널의 배열.
     * @param {Record<string, Float32Array>} parameters - 오디오 파라미터.
     * @returns {boolean} 프로세서를 계속 실행할지 여부. true를 반환하면 계속 실행됩니다.
     */
    process(inputs, outputs, parameters) {
      // 모노(단일 채널) 입력을 가정합니다.
      const inputChannelData = inputs[0][0];
  
      // 입력 데이터가 없으면 처리를 중단합니다.
      if (!inputChannelData) {
        return true;
      }
  
      // `sampleRate`는 AudioWorkletProcessor의 전역 컨텍스트에서 제공되는 현재 AudioContext의 샘플레이트입니다.
      const resampledData = resampleBuffer(inputChannelData, sampleRate, this.targetSampleRate);
      
      // Int16 형식으로 변환하여 ArrayBuffer를 얻습니다.
      const int16Data = convertFloat32ToInt16(resampledData);
  
      // 처리된 데이터가 있을 경우, 메인 스레드로 전송합니다.
      // 두 번째 인자로 [int16Data]를 전달하여 메모리 소유권을 이전(transfer)하므로 성능에 유리합니다.
      if (int16Data.byteLength > 0) {
        this.port.postMessage(int16Data, [int16Data]);
      }
      
      // 항상 true를 반환하여 프로세서가 계속 활성 상태를 유지하도록 합니다.
      return true;
    }
  }
  
  // 'audio-processor'라는 이름으로 커스텀 프로세서를 등록합니다.
  // 이 이름은 메인 스레드에서 AudioWorkletNode를 생성할 때 사용됩니다.
  registerProcessor('audio-processor', AudioProcessor);