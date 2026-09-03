import * as THREE from "three";

import type { FaceAvatar } from "./avatarLoader";
import type { AvatarPresence } from "./presence";

/** Procedural arm gestures while the bot speaks.
 *
 * Rig-agnostic by construction, the same trick avatarLoader's poseArmDown() uses:
 * instead of writing local euler angles -- which requires knowing how the rig
 * happens to orient each bone's local axes, and silently produces nonsense arms
 * when that guess is wrong -- every pose is expressed as the **world direction
 * the limb should point in**, and we compute the rotation that swings the bone's
 * rest direction onto it. Mixamo-style rigs (Ready Player Me, Avaturn, ...) point
 * a bone at its child along local +Y, which is the one assumption here.
 *
 * Two things make the motion read as natural rather than mechanical:
 *
 * - **The two arms are scheduled independently.** One shared gesture for both
 *   sides makes them move in lockstep or in strict alternation ("the arms take
 *   turns going up and down"), which no one does while talking. Each side has its
 *   own pose, its own timer and its own interval range, so they drift in and out
 *   of sync on their own.
 * - **Directions are what gets eased, not poses.** The limb always travels along a
 *   continuous arc between shapes, so there is no snap to smooth out afterwards.
 *
 * Shoulders are deliberately left to BodyAnimator (breathing): only the arm and
 * forearm bones are written here, so the two layers never fight over a bone.
 */

const ARM_BONES = ["LeftArm", "LeftForeArm", "RightArm", "RightForeArm"] as const;

/** Limb direction as [outward, up, forward], mirrored to each side. */
type Direction = readonly [number, number, number];

/** A pose is the upper arm's world direction plus an *elbow hinge*: how far the
 * forearm is bent, and in which plane.
 *
 * The forearm deliberately does NOT get a world direction of its own. An elbow
 * is a hinge -- it bends in a single plane -- so an independently chosen forearm
 * direction describes anatomically impossible configurations (bending sideways
 * or hyperextending), which is exactly what reads as "the arm folds in the wrong
 * place". Deriving the forearm from the upper arm and a bend angle makes those
 * configurations unrepresentable.
 */
interface ArmPose {
  arm: Direction;
  /** Elbow bend, degrees. 0 = straight. */
  bendDeg: number;
  /** Direction the forearm bends toward, projected perpendicular to the upper
   * arm: [outward, up, forward]. Forward (and slightly inward) while talking. */
  bendToward: Direction;
}

// Rest is the arms-down pose avatarLoader put the rig in -- with a few degrees of
// bend, because a relaxed arm never hangs board-straight.
const REST_BEND_DEG = 8;
const REST: ArmPose = { arm: [0.06, -1, 0], bendDeg: REST_BEND_DEG, bendToward: [-0.1, 0, 1] };

/** Single-arm poses, smallest first. Conversational gesturing is mostly forearm
 * movement close to the body -- the upper arm barely leaves the torso.
 *
 * Amplitudes were picked by measuring where the wrist actually lands on this
 * rig, not by eyeballing the vectors: at GESTURE_SCALE these lift the wrist by
 * ~6cm / ~9cm / ~14cm while the elbow stays put (y within 1cm of rest), which is
 * what bending at the elbow rather than swinging the whole arm looks like. */
const POSES: Record<string, ArmPose> = {
  rest: REST,
  // Hand drifts up near the waist, elbow just off the body.
  low: { arm: [0.13, -0.98, 0.12], bendDeg: 52, bendToward: [-0.25, 0.05, 1] },
  // Forearm angled forward at about navel height.
  mid: { arm: [0.18, -0.95, 0.16], bendDeg: 68, bendToward: [-0.3, 0.15, 1] },
  // The largest of the everyday gestures: forearm forward, palm presenting.
  open: { arm: [0.26, -0.9, 0.22], bendDeg: 84, bendToward: [-0.35, 0.25, 1] },
};

/** How far poses are taken from rest toward their full shape. Below 1 because
 * the poses above are already conversational -- this is the single knob for
 * "how much does it gesture at all". */
const GESTURE_SCALE = 0.62;

interface WeightedPose {
  pose: keyof typeof POSES;
  chance: number;
}

// Weighted so a hand is at rest most of the time: with two independent sides,
// something is almost always moving, and the stillness is what makes the
// gestures land instead of reading as fidgeting.
const SIDE_POSES: WeightedPose[] = [
  { pose: "rest", chance: 0.42 },
  { pose: "low", chance: 0.26 },
  { pose: "mid", chance: 0.2 },
  { pose: "open", chance: 0.12 },
];

/** Per-side re-roll interval. Different ranges per side so the two arms don't
 * lock into a rhythm with each other. */
const POSE_INTERVAL_S = [
  [2.6, 5.4],
  [3.1, 6.2],
] as const;

// Time constant of the swing between poses. Long: arms are heavy, and anything
// quicker looks like a puppet being yanked.
const SWING_TAU_S = 0.8;
// Extra elbow bend on stressed syllables, in degrees, scaled by how raised the
// arm already is (a beat on a dangling arm looks like a twitch).
const EMPHASIS_BEND_DEG = 7;
// Idle drift so a raised arm never looks frozen in place.
const DRIFT = 0.022;

const DEG = Math.PI / 180;

interface JointState {
  bone: THREE.Bone;
  restLocalQuaternion: THREE.Quaternion;
  /** Current world direction, eased toward the active pose's direction. */
  current: THREE.Vector3;
}

interface SideState {
  sign: number; // +1 for the avatar's left (bones sit at +X), -1 for its right
  arm: JointState | null;
  fore: JointState | null;
  pose: keyof typeof POSES;
  nextIn: number;
  /** Eased hinge state: bend angle in radians, and the (unnormalised) direction
   * the elbow bends toward, in world space. */
  bend: number;
  bendToward: THREE.Vector3;
}

function drift(t: number, seed: number): number {
  return Math.sin(t * 0.61 + seed * 2.3) * 0.6 + Math.sin(t * 1.09 + seed * 5.7) * 0.4;
}

function randomIn([min, max]: readonly [number, number]): number {
  return min + Math.random() * (max - min);
}

export class ArmGestures {
  private presence: AvatarPresence;
  private root: THREE.Object3D | null = null;
  private sides: SideState[] = [];

  private t = 0;

  private mouthOpenBaseline = 0;
  private emphasis = 0;

  private q1 = new THREE.Quaternion();
  private q2 = new THREE.Quaternion();
  private q3 = new THREE.Quaternion();
  private v1 = new THREE.Vector3();
  private target = new THREE.Vector3();

  constructor(presence: AvatarPresence) {
    this.presence = presence;
  }

  setAvatar(avatar: FaceAvatar | null) {
    this.sides = [];
    this.root = avatar?.scene ?? null;
    if (!avatar) return;

    const joint = (name: (typeof ARM_BONES)[number], sign: number): JointState | null => {
      const bone = avatar.scene.getObjectByName(name) as THREE.Bone | undefined;
      if (!bone) return null;
      // Both bones hang straight down at rest; the forearm's direction is
      // recomputed from the hinge every frame anyway.
      const rest = REST.arm;
      return {
        bone,
        // Captured after loadAvatar posed the arms down, so this is the pose
        // we're offsetting from.
        restLocalQuaternion: bone.quaternion.clone(),
        current: new THREE.Vector3(rest[0] * sign, rest[1], rest[2]).normalize(),
      };
    };

    const side = (sign: number, index: number): SideState => ({
      sign,
      arm: joint(sign > 0 ? "LeftArm" : "RightArm", sign),
      fore: joint(sign > 0 ? "LeftForeArm" : "RightForeArm", sign),
      pose: "rest",
      nextIn: randomIn(POSE_INTERVAL_S[index]),
      bend: REST_BEND_DEG * DEG,
      bendToward: new THREE.Vector3(REST.bendToward[0] * sign, REST.bendToward[1], REST.bendToward[2]),
    });

    this.sides = [side(1, 0), side(-1, 1)];
  }

  update(deltaSeconds: number) {
    if (!this.root || this.sides.length === 0) return;

    const dt = Math.min(Math.max(deltaSeconds, 0), 0.1);
    this.t += dt;

    const speaking = this.presence.mode === "speaking";

    const mouthOpen = this.presence.botSpeaking ? this.presence.mouthOpen : 0;
    this.mouthOpenBaseline += (mouthOpen - this.mouthOpenBaseline) * (1 - Math.exp(-dt / 0.6));
    const peak = Math.min(Math.max(mouthOpen - this.mouthOpenBaseline, 0), 1);
    this.emphasis += (peak - this.emphasis) * (1 - Math.exp(-dt / 0.12));

    // Parents (spine, shoulders) were animated by BodyAnimator earlier this
    // frame; refresh world matrices before reading them.
    this.root.updateWorldMatrix(true, true);

    const ease = 1 - Math.exp(-dt / SWING_TAU_S);

    for (const [index, side] of this.sides.entries()) {
      this.advancePose(side, index, dt, speaking);

      // Hands come down whenever the bot isn't talking.
      const pose = speaking ? POSES[side.pose] : REST;

      if (!side.arm) continue;

      this.easeArm(side.arm, pose.arm, side.sign, GESTURE_SCALE, ease, index * 3 + 1);
      this.swing(side.arm);
      side.arm.bone.updateWorldMatrix(false, false); // the forearm reads this below

      if (!side.fore) continue;

      // How far this arm is from hanging down: beats only apply to raised arms.
      const raised = Math.min(
        Math.max(1 - side.arm.current.dot(this.v1.set(0, -1, 0)), 0),
        1
      );
      this.easeHinge(side, pose, GESTURE_SCALE, ease, this.emphasis * EMPHASIS_BEND_DEG * raised);
      this.foreDirection(side, side.fore.current);
      this.swing(side.fore);
    }
  }

  private advancePose(side: SideState, index: number, dt: number, rollAllowed: boolean) {
    if (!rollAllowed) return;

    side.nextIn -= dt;
    if (side.nextIn > 0) return;

    const total = SIDE_POSES.reduce((sum, p) => sum + p.chance, 0);
    let roll = Math.random() * total;
    for (const candidate of SIDE_POSES) {
      roll -= candidate.chance;
      if (roll <= 0) {
        side.pose = candidate.pose;
        break;
      }
    }
    side.nextIn = randomIn(POSE_INTERVAL_S[index] ?? POSE_INTERVAL_S[0]);
  }

  /** Move the upper arm's current world direction toward its (scaled) pose
   * target, plus idle drift. */
  private easeArm(
    joint: JointState,
    pose: Direction,
    sign: number,
    scale: number,
    ease: number,
    seed: number
  ) {
    const rest = REST.arm;
    this.target
      .set(
        (rest[0] + (pose[0] - rest[0]) * scale) * sign,
        rest[1] + (pose[1] - rest[1]) * scale,
        rest[2] + (pose[2] - rest[2]) * scale
      )
      .normalize()
      .addScaledVector(
        this.v1.set(
          drift(this.t, seed) * sign,
          drift(this.t, seed + 0.5),
          drift(this.t, seed + 1.5)
        ),
        DRIFT
      );
    joint.current.lerp(this.target, ease).normalize();
  }

  /** Ease the elbow hinge: bend angle and the plane it bends in. */
  private easeHinge(
    side: SideState,
    pose: ArmPose,
    scale: number,
    ease: number,
    extraBendDeg: number
  ) {
    const bendTarget =
      (REST_BEND_DEG + (pose.bendDeg - REST_BEND_DEG) * scale + extraBendDeg) * DEG;
    side.bend += (bendTarget - side.bend) * ease;

    this.target.set(pose.bendToward[0] * side.sign, pose.bendToward[1], pose.bendToward[2]);
    side.bendToward.lerp(this.target, ease);
  }

  /** Forearm world direction: the upper arm's direction, rotated by the bend
   * angle within the hinge plane. Always a valid elbow, by construction. */
  private foreDirection(side: SideState, out: THREE.Vector3) {
    const armDir = side.arm!.current;
    // Component of the bend direction perpendicular to the upper arm.
    this.v1.copy(side.bendToward).addScaledVector(armDir, -side.bendToward.dot(armDir));
    if (this.v1.lengthSq() < 1e-6) {
      out.copy(armDir);
      return;
    }
    this.v1.normalize();
    out
      .copy(armDir)
      .multiplyScalar(Math.cos(side.bend))
      .addScaledVector(this.v1, Math.sin(side.bend))
      .normalize();
  }

  /** Rotate `joint` so its bone points along `joint.current` in world space. */
  private swing(joint: JointState) {
    const parent = joint.bone.parent;
    if (!parent) return;

    const parentWorld = this.q1.copy(parent.getWorldQuaternion(this.q3));
    const restWorld = this.q2.copy(parentWorld).multiply(joint.restLocalQuaternion);
    const restDir = this.v1.set(0, 1, 0).applyQuaternion(restWorld).normalize();

    const delta = this.q3.setFromUnitVectors(restDir, joint.current);
    const newWorld = delta.multiply(restWorld);
    joint.bone.quaternion.copy(parentWorld.invert().multiply(newWorld));
  }
}
