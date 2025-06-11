class AudioProcessor extends AudioWorkletProcessor {
  process(inputs, outputs) {
    const input = inputs[0]
    if (input.length > 0) {
      const inputData = input[0]
      const int16Data = new Int16Array(inputData.length)
      
      for (let i = 0; i < inputData.length; i++) {
        int16Data[i] = Math.min(1, inputData[i]) * 0x7FFF
      }
      
      this.port.postMessage({ audioData: int16Data.buffer }, [int16Data.buffer])
    }
    return true
  }
}

registerProcessor('audio-processor', AudioProcessor) 