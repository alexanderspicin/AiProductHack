import type { FaceAvatar } from "./avatarLoader";

/** Independent sources of morph-target weights, summed per frame.
 *
 * Without this, whoever calls `setAvatar.setBlendshapes()` last wins: the viseme
 * driver replaces the whole weight map on every event, so a blink or a raised
 * brow written by another layer would be silently overwritten (and vice versa).
 * Each layer publishes only its own shapes; the compositor adds them up, clamps,
 * and is the single writer to the mesh.
 */
export type BlendshapeLayer = "viseme" | "idle";

export class BlendshapeCompositor {
  private avatar: FaceAvatar | null = null;
  private layers = new Map<BlendshapeLayer, Record<string, number>>();
  private appliedKeys = new Set<string>();

  setAvatar(avatar: FaceAvatar | null) {
    this.avatar = avatar;
  }

  /** Replace `layer`'s contribution. Shapes absent from `weights` are dropped. */
  set(layer: BlendshapeLayer, weights: Record<string, number>) {
    this.layers.set(layer, weights);
  }

  apply() {
    if (!this.avatar) return;

    // Start every previously written shape at 0 so shapes a layer stopped
    // publishing get actively released instead of freezing at their last value.
    const summed: Record<string, number> = {};
    for (const key of this.appliedKeys) summed[key] = 0;

    for (const weights of this.layers.values()) {
      for (const [key, weight] of Object.entries(weights)) {
        summed[key] = (summed[key] ?? 0) + weight;
      }
    }

    this.appliedKeys.clear();
    for (const key of Object.keys(summed)) {
      summed[key] = Math.min(1, Math.max(0, summed[key]));
      if (summed[key] > 0.001) this.appliedKeys.add(key);
    }

    this.avatar.setBlendshapes(summed);
  }
}
