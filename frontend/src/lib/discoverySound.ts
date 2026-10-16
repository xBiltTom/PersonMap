let audioContext: AudioContext | null = null;
let lastPlayedAt = 0;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined" || typeof window.AudioContext === "undefined") return null;
  try {
    audioContext ??= new window.AudioContext();
    return audioContext;
  } catch {
    return null;
  }
}

export function isDiscoverySoundUnlocked(): boolean {
  return audioContext?.state === "running";
}

/** Call directly from a user gesture so browsers allow later discovery alerts. */
export async function unlockDiscoverySound(): Promise<boolean> {
  const context = getAudioContext();
  if (!context) return false;

  try {
    await context.resume();
    return context.state === "running";
  } catch {
    return false;
  }
}

function playTone(context: AudioContext, frequency: number, startAt: number, duration: number) {
  const oscillator = context.createOscillator();
  const gain = context.createGain();

  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(frequency, startAt);
  oscillator.frequency.exponentialRampToValueAtTime(frequency * 0.9, startAt + duration);
  gain.gain.setValueAtTime(0.0001, startAt);
  gain.gain.exponentialRampToValueAtTime(0.055, startAt + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);

  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(startAt);
  oscillator.stop(startAt + duration + 0.02);
}

/** A short rising two-note cue for a new batch of findings. */
export function playDiscoverySound(): boolean {
  const context = audioContext;
  if (!context || context.state !== "running") return false;

  const now = performance.now();
  if (now - lastPlayedAt < 800) return false;
  lastPlayedAt = now;

  const startAt = context.currentTime + 0.01;
  playTone(context, 740, startAt, 0.13);
  playTone(context, 988, startAt + 0.09, 0.16);
  return true;
}
