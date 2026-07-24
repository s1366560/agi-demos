/**
 * AudioWorklet Processor for voice capture.
 *
 * Captures microphone input, resamples from the browser native sample rate
 * down to 16000 Hz, converts Float32 samples to Int16, and posts buffered
 * chunks of 4096 samples to the renderer.
 */

class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sampleRate = 48000;
    this.targetSampleRate = 16000;
    this.bufferSize = 4096;
    this.outputBuffer = new Int16Array(this.bufferSize);
    this.outputIndex = 0;
    this.resamplePosition = 0;
    this.port.onmessage = (event) => {
      if (
        event.data?.type === 'config' &&
        typeof event.data.sampleRate === 'number' &&
        event.data.sampleRate > 0
      ) {
        this.sampleRate = event.data.sampleRate;
      }
    };
  }

  float32ToInt16(sample) {
    const clamped = Math.max(-1, Math.min(1, sample));
    return clamped < 0
      ? Math.max(-32768, Math.round(clamped * 32768))
      : Math.min(32767, Math.round(clamped * 32767));
  }

  process(inputs) {
    const channelData = inputs[0]?.[0];
    if (!channelData?.length) return true;
    const ratio = this.sampleRate / this.targetSampleRate;
    while (this.resamplePosition < channelData.length) {
      const index = Math.floor(this.resamplePosition);
      const fraction = this.resamplePosition - index;
      const current = channelData[index];
      const next = channelData[index + 1] ?? current;
      const interpolated = current + fraction * (next - current);
      this.outputBuffer[this.outputIndex] = this.float32ToInt16(interpolated);
      this.outputIndex += 1;
      if (this.outputIndex >= this.bufferSize) {
        this.port.postMessage(this.outputBuffer.slice());
        this.outputIndex = 0;
      }
      this.resamplePosition += ratio;
    }
    this.resamplePosition -= channelData.length;
    return true;
  }
}

registerProcessor('audio-processor', AudioProcessor);
