// Adapted from alexanderspicin/AiProductHack, commit 92edfbde; local integration only.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

// Plain glTF loader (no VRM layer) so we can drive a mesh's native morph targets
// directly by name -- no remapping layer, just a case-insensitive lookup into
// whatever morph targets the mesh actually has. Built for Ready Player Me avatars
// downloaded with `?morphTargets=ARKit,Oculus Visemes` (see README): the backend's
// viseme analysis outputs Oculus viseme names (viseme_sil, viseme_aa, ...) as the
// primary driver, with the frontend's own jawOpen (ARKit) fallback for when a real
// event is late. A single glTF can spread the same shape name across several
// meshes (head/teeth/eyes), so the lookup covers all of them.

// This project doesn't bundle any animation clips, so a skinned avatar renders in
// its skeleton's rest pose -- for Mixamo-rig-compatible humanoids (Ready Player Me,
// Avaturn, the TalkingHead sample avatars, ...) that rest pose is a T-pose.
//
// Rotating a bone by a hardcoded number of degrees on some hardcoded axis (an
// earlier version of this function did that) is guessing at the rig's bone-axis
// convention and breaks on rigs where that guess is wrong (arms end up pointing
// the wrong way instead of down). This version is rig-agnostic: it reads the
// bone's actual current WORLD-space pointing direction, computes the rotation
// needed to swing that direction to point down, and applies just that delta --
// works regardless of how the rig's local axes are set up. Only the upper-arm
// bone needs this; the forearm/hand/fingers are its children and swing down
// with it automatically.
function poseArmDown(root: THREE.Object3D, boneName: string) {
  const bone = root.getObjectByName(boneName) as THREE.Bone | undefined;
  if (!bone || !bone.parent) return;

  root.updateWorldMatrix(true, true);

  const worldQuat = bone.getWorldQuaternion(new THREE.Quaternion());
  // Mixamo-style rigs point a bone at its child along local +Y.
  const currentWorldDir = new THREE.Vector3(0, 1, 0).applyQuaternion(worldQuat).normalize();
  const targetWorldDir = new THREE.Vector3(0, -1, 0);

  const deltaWorld = new THREE.Quaternion().setFromUnitVectors(currentWorldDir, targetWorldDir);
  const newWorldQuat = deltaWorld.multiply(worldQuat);

  const parentWorldQuat = bone.parent.getWorldQuaternion(new THREE.Quaternion());
  const newLocalQuat = parentWorldQuat.invert().multiply(newWorldQuat);

  bone.quaternion.copy(newLocalQuat);
}

function poseArmsDown(root: THREE.Object3D) {
  poseArmDown(root, "LeftArm");
  poseArmDown(root, "RightArm");
}

export interface FaceAvatar {
  scene: THREE.Object3D;
  setBlendshapes(weights: Record<string, number>): void;
}

export async function loadAvatar(scene: THREE.Scene, url = "/models/avatar.glb"): Promise<FaceAvatar | null> {
  const loader = new GLTFLoader();

  try {
    const gltf = await loader.loadAsync(url);

    const lookup = new Map<string, Array<{ mesh: THREE.Mesh; index: number }>>();
    gltf.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh || !mesh.morphTargetDictionary || !mesh.morphTargetInfluences) return;
      for (const [name, index] of Object.entries(mesh.morphTargetDictionary)) {
        const key = name.toLowerCase();
        const entries = lookup.get(key) ?? [];
        entries.push({ mesh, index });
        lookup.set(key, entries);
      }
    });

    poseArmsDown(gltf.scene);
    scene.add(gltf.scene);

    return {
      scene: gltf.scene,
      setBlendshapes(weights: Record<string, number>) {
        for (const [name, weight] of Object.entries(weights)) {
          const targets = lookup.get(name.toLowerCase());
          if (!targets) continue;
          for (const { mesh, index } of targets) {
            mesh.morphTargetInfluences![index] = weight;
          }
        }
      },
    };
  } catch (err) {
    console.warn(`No avatar loaded from ${url} (place one there to see a face):`, err);
    return null;
  }
}
