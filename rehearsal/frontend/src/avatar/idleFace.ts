// Adapted from alexanderspicin/AiProductHack, commit 92edfbde; local integration only.
import type { BlendshapeCompositor } from "./blendshapeCompositor";
import type { AvatarPresence } from "./presence";

/** Everything the face does that isn't lip-sync: blinking, gaze, brows.
 *
 * Publishes into the compositor's "idle" layer, so it composes with the viseme
 * layer instead of fighting it. Blinking is the single biggest cue that an avatar
 * isn't a mannequin, which is why it's here rather than in some later phase.
 *
 * Morph names are published in both conventions ARKit exports use in the wild
 * ("eyeBlinkLeft" and "eyeBlink_L"): avatarLoader looks names up case-
 * insensitively and silently ignores ones the mesh doesn't have, so emitting
 * both aliases costs nothing and works across avatar sources.
 */

const BLINK_DURATION_S = 0.12;
const DOUBLE_BLINK_CHANCE = 0.15;
const SACCADE_DURATION_S = 0.06; // real saccades are near-instant
const RECENTRE_CHANCE = 0.35; // fraction of saccades that go back to the camera

// Blink/gaze cadence per conversational state. A listener blinks a little more
// and holds the speaker's gaze; a speaker looks away more often.
const TIMING_BY_MODE = {
  speaking: { blink: [2.8, 5.5], saccade: [0.9, 2.2], gazeRange: 0.32 },
  listening: { blink: [2.2, 4.5], saccade: [1.8, 4.0], gazeRange: 0.16 },
  idle: { blink: [3.2, 7.0], saccade: [1.5, 3.5], gazeRange: 0.26 },
} as const;

// How slowly state-dependent expressions (listening brow, resting smile) ease
// between modes.
const MODE_EASE_TAU_S = 0.4;

const BROW_BASE = 0.04;
const BROW_LISTENING = 0.12;
const BROW_EMPHASIS = 0.35;
const IDLE_SMILE = 0.05;

function randomIn([min, max]: readonly [number, number]): number {
  return min + Math.random() * (max - min);
}

function sideAliases(base: string): [string, string] {
  // "eyeBlinkLeft" / "eyeBlink_L" style aliases.
  if (base.endsWith("Left")) return [base, `${base.slice(0, -4)}_L`];
  if (base.endsWith("Right")) return [base, `${base.slice(0, -5)}_R`];
  return [base, base];
}

export class IdleFace {
  private presence: AvatarPresence;
  private compositor: BlendshapeCompositor;

  private blinkIn = 1.5;
  private blinkElapsed = Number.POSITIVE_INFINITY;
  private blinksQueued = 0;

  private gazeIn = 1.0;
  private gazeFrom: [number, number] = [0, 0];
  private gazeTo: [number, number] = [0, 0];
  private gazeElapsed = SACCADE_DURATION_S;

  private mouthOpenBaseline = 0;
  private emphasis = 0;
  // Eased, not switched, for the same reason as the body's listen tilt: the
  // mode can change in a single frame on a barge-in.
  private listenBrow = 0;
  private idleSmile = 0;

  constructor(presence: AvatarPresence, compositor: BlendshapeCompositor) {
    this.presence = presence;
    this.compositor = compositor;
  }

  update(deltaSeconds: number) {
    const dt = Math.min(Math.max(deltaSeconds, 0), 0.1);
    const mode = this.presence.mode;
    const timing = TIMING_BY_MODE[mode];

    this.advanceBlink(dt, timing.blink);
    this.advanceGaze(dt, timing.saccade, timing.gazeRange);

    const mouthOpen = this.presence.botSpeaking ? this.presence.mouthOpen : 0;
    this.mouthOpenBaseline += (mouthOpen - this.mouthOpenBaseline) * (1 - Math.exp(-dt / 0.6));
    const peak = Math.min(Math.max(mouthOpen - this.mouthOpenBaseline, 0), 1);
    this.emphasis += (peak - this.emphasis) * (1 - Math.exp(-dt / 0.08));

    const ease = 1 - Math.exp(-dt / MODE_EASE_TAU_S);
    this.listenBrow += ((mode === "listening" ? BROW_LISTENING : 0) - this.listenBrow) * ease;
    this.idleSmile += ((mode === "idle" ? IDLE_SMILE : 0) - this.idleSmile) * ease;

    const weights: Record<string, number> = {};
    const add = (name: string, value: number) => {
      if (value <= 0.001) return;
      for (const alias of sideAliases(name)) weights[alias] = value;
    };

    const blink = this.blinkWeight();
    add("eyeBlinkLeft", blink);
    add("eyeBlinkRight", blink);

    const [gazeX, gazeY] = this.gazeNow();
    // Positive x = the avatar looks to its own left.
    if (gazeX > 0) {
      add("eyeLookOutLeft", gazeX);
      add("eyeLookInRight", gazeX);
    } else {
      add("eyeLookInLeft", -gazeX);
      add("eyeLookOutRight", -gazeX);
    }
    if (gazeY > 0) {
      add("eyeLookUpLeft", gazeY);
      add("eyeLookUpRight", gazeY);
    } else {
      add("eyeLookDownLeft", -gazeY);
      add("eyeLookDownRight", -gazeY);
    }

    const brow = BROW_BASE + this.listenBrow + this.emphasis * BROW_EMPHASIS;
    add("browInnerUp", brow);
    add("browOuterUpLeft", brow * 0.6);
    add("browOuterUpRight", brow * 0.6);

    // A hint of a smile at rest, so the neutral face isn't a blank stare. Fades
    // out while speaking, where it would fight the viseme mouth shapes.
    add("mouthSmileLeft", this.idleSmile);
    add("mouthSmileRight", this.idleSmile);

    this.compositor.set("idle", weights);
  }

  private advanceBlink(dt: number, interval: readonly [number, number]) {
    this.blinkElapsed += dt;

    if (this.blinksQueued > 0 && this.blinkElapsed >= BLINK_DURATION_S) {
      this.blinksQueued -= 1;
      this.blinkElapsed = 0;
      return;
    }

    this.blinkIn -= dt;
    if (this.blinkIn <= 0) {
      this.blinkElapsed = 0;
      this.blinksQueued = Math.random() < DOUBLE_BLINK_CHANCE ? 1 : 0;
      this.blinkIn = randomIn(interval) + this.blinksQueued * BLINK_DURATION_S * 2;
    }
  }

  private blinkWeight(): number {
    const p = this.blinkElapsed / BLINK_DURATION_S;
    if (p < 0 || p > 1) return 0;
    // Lids snap shut and open a little slower, like the real thing.
    return p < 0.4 ? p / 0.4 : 1 - (p - 0.4) / 0.6;
  }

  private advanceGaze(dt: number, interval: readonly [number, number], range: number) {
    this.gazeElapsed += dt;
    this.gazeIn -= dt;
    if (this.gazeIn > 0) return;

    this.gazeFrom = this.gazeNow();
    this.gazeTo =
      Math.random() < RECENTRE_CHANCE
        ? [0, 0]
        : [(Math.random() * 2 - 1) * range, (Math.random() * 2 - 1) * range * 0.6];
    this.gazeElapsed = 0;
    this.gazeIn = randomIn(interval);
  }

  private gazeNow(): [number, number] {
    const p = Math.min(this.gazeElapsed / SACCADE_DURATION_S, 1);
    return [
      this.gazeFrom[0] + (this.gazeTo[0] - this.gazeFrom[0]) * p,
      this.gazeFrom[1] + (this.gazeTo[1] - this.gazeFrom[1]) * p,
    ];
  }
}
