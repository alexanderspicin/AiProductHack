import type { BlendshapeCompositor } from "./blendshapeCompositor";
import type { AvatarPresence } from "./presence";
import type { AvatarEvent } from "../protocol/avatarProtocol";

const EVENT_STALE_MS = 250;
// Exponential smoothing time constant. Applied per *second* rather than per
// frame so the motion is identical at 60/90/144Hz and doesn't stutter when a
// frame is dropped. Short enough (~45ms) not to smear articulation, long enough
// to round off the steps between backend samples.
const SMOOTHING_TAU_S = 0.045;

// Synthetic mouth-open oscillation used as a last-resort fallback if a viseme
// event is ever late/dropped on the wire (real events normally arrive alongside
// each audio chunk with no added latency, computed locally on the backend -- see
// backend/app/avatar/viseme_analysis.py). There's no way to read the bot's actual
// audio client-side to compute a better fallback here: `@pipecat-ai/websocket-
// transport` plays bot audio through an internal wavtools player and never fires
// `onTrackStarted` for it (that's a WebRTC-transport-only callback), so there's no
// MediaStreamTrack to run an AnalyserNode on.
const TALKING_OSCILLATION_HZ = 3.5;

export class VisemeDriver {
  private compositor: BlendshapeCompositor;
  private presence: AvatarPresence;
  private currentUtteranceId = 0;
  private targetWeights: Record<string, number> = {};
  private currentWeights: Record<string, number> = {};
  private lastEventAt = 0;
  private mouthOpenTarget = 0;
  // Set once the backend says this utterance's visemes are done. The backend
  // keeps emitting until the audio it sent has actually been paced out, so any
  // "bot is still speaking" time after that is buffer drain -- flapping the jaw
  // through it would be exactly the artifact this fallback exists to avoid.
  private playbackDone = true;

  constructor(presence: AvatarPresence, compositor: BlendshapeCompositor) {
    this.presence = presence;
    this.compositor = compositor;
  }

  handleAvatarEvent(event: AvatarEvent) {
    if (event.type === "viseme") {
      if (event.utterance_id !== this.currentUtteranceId) return; // stale, drop
      this.targetWeights = event.blendshapes ?? { jawOpen: event.mouth_open };
      this.mouthOpenTarget = event.mouth_open;
      this.lastEventAt = performance.now();
    } else if (event.type === "playback_start") {
      this.currentUtteranceId = event.utterance_id;
      this.targetWeights = {};
      this.mouthOpenTarget = 0;
      this.playbackDone = false;
    } else if (event.type === "playback_end" || event.type === "interrupt") {
      if (event.utterance_id === this.currentUtteranceId) {
        this.targetWeights = {};
        this.mouthOpenTarget = 0;
        this.playbackDone = true;
      }
    }
  }

  update(deltaSeconds: number) {
    const isBotSpeaking = this.presence.botSpeaking;
    const eventIsStale = performance.now() - this.lastEventAt > EVENT_STALE_MS;
    if (eventIsStale && isBotSpeaking && !this.playbackDone) {
      const t = performance.now() / 1000;
      const oscillation = (Math.sin(2 * Math.PI * TALKING_OSCILLATION_HZ * t) + 1) / 2;
      // Kept within the same amplitude range as the real jawOpen the backend
      // sends, so the fallback (if it ever kicks in) doesn't read as the mouth
      // suddenly being flung wide open.
      this.targetWeights = { jawOpen: 0.04 + 0.16 * oscillation };
    } else if (eventIsStale && (!isBotSpeaking || this.playbackDone)) {
      this.targetWeights = {};
    }

    // Interpolate every key that's either currently active or being targeted, then
    // let ones that reached ~0 drop out so this map doesn't grow unboundedly.
    const keys = new Set([...Object.keys(this.currentWeights), ...Object.keys(this.targetWeights)]);
    const alpha = 1 - Math.exp(-Math.max(deltaSeconds, 0) / SMOOTHING_TAU_S);
    const applied: Record<string, number> = {};
    for (const key of keys) {
      const current = this.currentWeights[key] ?? 0;
      const target = this.targetWeights[key] ?? 0;
      const next = current + (target - current) * alpha;
      applied[key] = next;
      if (Math.abs(next) > 0.001) this.currentWeights[key] = next;
      else delete this.currentWeights[key];
    }

    // Publish the smoothed mouth opening for the idle layers: it's the cheapest
    // "which syllable is stressed" signal we have, and drives the emphasis nod
    // and brow raise. Taken from the event's own `mouth_open` (unscaled 0..1),
    // not from the jawOpen morph weight, which the backend deliberately damps.
    const target = eventIsStale ? 0 : this.mouthOpenTarget;
    this.presence.mouthOpen += (target - this.presence.mouthOpen) * alpha;

    this.compositor.set("viseme", applied);
  }
}
