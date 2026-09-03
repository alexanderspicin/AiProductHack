import * as THREE from "three";

import type { FaceAvatar } from "./avatarLoader";
import type { AvatarPresence } from "./presence";

/** Procedural idle body motion: breathing, head micro-movement, weight shift.
 *
 * Everything here is *additive on top of the rest pose captured at load time*.
 * That matters: avatarLoader's poseArmsDown() writes bone quaternions directly,
 * so the rest pose we must offset from is the posed one, not the glTF's T-pose --
 * and writing absolute rotations every frame (rather than accumulating onto the
 * bone's current value) is what keeps the avatar from slowly drifting away.
 *
 * No animation clips are bundled, so this is all analytic: sums of sines at
 * mutually incommensurate frequencies, which reads as organic without needing a
 * noise library, and is exactly reproducible/debuggable.
 */

// Mixamo-style bone names (Ready Player Me, Avaturn, ...).
const BONE_NAMES = [
  "Head",
  "Neck",
  "Spine2",
  "Spine1",
  "Spine",
  "Hips",
  "LeftShoulder",
  "RightShoulder",
] as const;
type BoneName = (typeof BONE_NAMES)[number];

const DEG = Math.PI / 180;

const BREATHS_PER_SECOND = 0.25; // ~15 breaths/min, resting adult

// Motion is scaled by conversational state: a listener holds much stiller than
// someone mid-sentence, and that contrast is most of what reads as "alive".
const AMPLITUDE_BY_MODE = { speaking: 1.0, listening: 0.5, idle: 0.7 };

// Sideways head tilt while listening, and how slowly it eases in/out. The ease
// has to be slow enough that a barge-in (speaking -> listening in one frame)
// reads as the head settling, not twitching.
const LISTEN_TILT_DEG = 2.2;
const LISTEN_TILT_TAU_S = 0.45;

// Slow lateral weight shift (level 2). Very low frequency on purpose -- anything
// faster looks like swaying rather than standing.
const WEIGHT_SHIFT_HZ = 0.07;
const WEIGHT_SHIFT_DEG = 1.6;
const WEIGHT_SHIFT_METERS = 0.012;

interface RestPose {
  bone: THREE.Bone;
  quaternion: THREE.Quaternion;
  position: THREE.Vector3;
}

/** Sum of three sines with irrational frequency ratios: never repeats, stays in
 * [-1, 1], and costs nothing. `seed` decorrelates the channels. */
function wobble(t: number, seed: number): number {
  return (
    (Math.sin(t * 0.83 + seed * 1.7) * 0.5 +
      Math.sin(t * 1.47 + seed * 4.1) * 0.33 +
      Math.sin(t * 2.71 + seed * 9.3) * 0.17) /
    1.0
  );
}

export class BodyAnimator {
  private rest = new Map<BoneName, RestPose>();
  private presence: AvatarPresence;
  private t = 0;
  private amplitude = AMPLITUDE_BY_MODE.idle;
  // Head tilt of a listener. Smoothed rather than switched: the mode can flip
  // instantly (barge-in, or VAD toggling around the edge of a phrase) and
  // applying the tilt as a step made the head visibly snap sideways.
  private listenTilt = 0;
  // Slow-moving average of mouth opening; subtracting it from the current value
  // isolates the *peaks* (stressed vowels) rather than "is talking at all".
  private mouthOpenBaseline = 0;
  private emphasis = 0;
  private scratchEuler = new THREE.Euler();
  private scratchQuat = new THREE.Quaternion();

  constructor(presence: AvatarPresence) {
    this.presence = presence;
  }

  setAvatar(avatar: FaceAvatar | null) {
    this.rest.clear();
    if (!avatar) return;

    for (const name of BONE_NAMES) {
      const bone = avatar.scene.getObjectByName(name) as THREE.Bone | undefined;
      if (!bone) continue; // rig without this bone: that channel just does nothing
      this.rest.set(name, {
        bone,
        quaternion: bone.quaternion.clone(),
        position: bone.position.clone(),
      });
    }
  }

  update(deltaSeconds: number) {
    if (this.rest.size === 0) return;

    const dt = Math.min(Math.max(deltaSeconds, 0), 0.1); // clamp: tab-switch spikes
    this.t += dt;

    const mode = this.presence.mode;
    this.amplitude += (AMPLITUDE_BY_MODE[mode] - this.amplitude) * (1 - Math.exp(-dt / 0.5));
    const tiltTarget = mode === "listening" ? LISTEN_TILT_DEG * DEG : 0;
    this.listenTilt += (tiltTarget - this.listenTilt) * (1 - Math.exp(-dt / LISTEN_TILT_TAU_S));

    const mouthOpen = this.presence.botSpeaking ? this.presence.mouthOpen : 0;
    this.mouthOpenBaseline += (mouthOpen - this.mouthOpenBaseline) * (1 - Math.exp(-dt / 0.6));
    const peak = Math.min(Math.max(mouthOpen - this.mouthOpenBaseline, 0), 1);
    this.emphasis += (peak - this.emphasis) * (1 - Math.exp(-dt / 0.08));

    const t = this.t;
    const a = this.amplitude;

    const breath = Math.sin(2 * Math.PI * BREATHS_PER_SECOND * t);
    const shift = Math.sin(2 * Math.PI * WEIGHT_SHIFT_HZ * t);

    // Head micro-movement, split across neck and head so the chain bends instead
    // of the head pivoting alone.
    const headYaw = wobble(t, 1) * 2.6 * DEG * a;
    const headPitch = wobble(t, 2) * 1.5 * DEG * a;
    const headRoll = wobble(t, 3) * 1.2 * DEG * a;
    // A listener tilts their head slightly -- a small constant bias, not noise.
    // Chin dips a touch on stressed vowels: the "speaking with intent" cue.
    const emphasisNod = this.emphasis * 1.8 * DEG;

    this.applyRotation(
      "Head",
      headPitch * 0.6 + emphasisNod,
      headYaw * 0.6,
      headRoll * 0.6 + this.listenTilt
    );
    this.applyRotation("Neck", headPitch * 0.4 + breath * 0.3 * DEG * a, headYaw * 0.4, headRoll * 0.4);

    // Torso: breathing, plus a counter-rotation against the hips so the weight
    // shift moves the body without dragging the head off-centre.
    this.applyRotation("Spine2", breath * 0.9 * DEG, -shift * WEIGHT_SHIFT_DEG * 0.35 * DEG * a, 0);
    this.applyRotation("Spine1", breath * 0.7 * DEG, -shift * WEIGHT_SHIFT_DEG * 0.35 * DEG * a, 0);
    this.applyRotation("Spine", 0, -shift * WEIGHT_SHIFT_DEG * 0.3 * DEG * a, 0);

    this.applyRotation("Hips", 0, shift * WEIGHT_SHIFT_DEG * DEG * a, 0);
    this.applyPositionX("Hips", shift * WEIGHT_SHIFT_METERS * a);

    // Shoulders ride the breath, in opposite roll directions (they rise together
    // but the rig mirrors the axis).
    this.applyRotation("LeftShoulder", 0, 0, breath * 0.8 * DEG);
    this.applyRotation("RightShoulder", 0, 0, -breath * 0.8 * DEG);
  }

  private applyRotation(name: BoneName, pitch: number, yaw: number, roll: number) {
    const rest = this.rest.get(name);
    if (!rest) return;
    this.scratchEuler.set(pitch, yaw, roll);
    this.scratchQuat.setFromEuler(this.scratchEuler);
    rest.bone.quaternion.copy(rest.quaternion).multiply(this.scratchQuat);
  }

  private applyPositionX(name: BoneName, offset: number) {
    const rest = this.rest.get(name);
    if (!rest) return;
    rest.bone.position.set(rest.position.x + offset, rest.position.y, rest.position.z);
  }
}
