// AudioWorklet: junta amostras do microfone em quadros de ~20 ms e envia ao app.
class TitanCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = Math.round(sampleRate * 0.02);
    this.buf = new Float32Array(this.frame);
    this.pos = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.pos++] = ch[i];
      if (this.pos === this.frame) {
        this.port.postMessage(this.buf.slice(0));
        this.pos = 0;
      }
    }
    return true;
  }
}
registerProcessor("titan-capture", TitanCapture);
