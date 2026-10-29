// Tiny synthesised sound effects (Web Audio), no files. Off when the player mutes.
import { store } from "../common.js";

let ctx = null;
export let muted = store.get("cp-muted") === "1";
export function setMuted(m) { muted = m; store.set("cp-muted", m ? "1" : "0"); }

function tone(freq, start, dur, type = "sine", gain = 0.12) {
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, ctx.currentTime + start);
  g.gain.setValueAtTime(0, ctx.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  o.connect(g).connect(ctx.destination);
  o.start(ctx.currentTime + start); o.stop(ctx.currentTime + start + dur + 0.05);
}

const SOUNDS = {
  cash: () => { tone(880, 0, 0.12, "triangle"); tone(1320, 0.08, 0.18, "triangle"); },
  review: () => { tone(520, 0, 0.18, "square", 0.06); tone(440, 0.2, 0.22, "square", 0.06); },
  block: () => { tone(220, 0, 0.35, "sawtooth", 0.09); tone(160, 0.12, 0.45, "sawtooth", 0.08); },
  click: () => tone(660, 0, 0.05, "triangle", 0.05),
  level: () => { tone(300, 0, 0.15, "square", 0.07); tone(300, 0.2, 0.15, "square", 0.07); tone(300, 0.4, 0.15, "square", 0.07); },
  win: () => [523, 659, 784, 1046].forEach((f, i) => tone(f, i * 0.11, 0.3, "triangle", 0.1)),
  lose: () => [392, 330, 262].forEach((f, i) => tone(f, i * 0.16, 0.35, "sine", 0.1)),
  ring: () => { for (let i = 0; i < 2; i++) { tone(440, i * 0.3, 0.12, "sine", 0.07); tone(480, i * 0.3, 0.12, "sine", 0.07); } },
};

export function play(name) {
  if (muted) return;
  try {
    ctx ??= new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    SOUNDS[name]?.();
  } catch { /* no audio: fine */ }
}
