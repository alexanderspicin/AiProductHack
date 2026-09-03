/** Shared "what is the avatar doing right now" state.
 *
 * Written by main.ts (from the Pipecat speaking callbacks) and by VisemeDriver
 * (mouth opening, 50 times a second), read by every idle-motion layer. Keeping
 * it in one object means the layers don't need to know about each other or about
 * the transport -- they just look at the current mode and amplitude.
 */

export type PresenceMode = "speaking" | "listening" | "idle";

export class AvatarPresence {
  botSpeaking = false;
  userSpeaking = false;
  /** Current mouth opening 0..1, as sent by the backend viseme events. */
  mouthOpen = 0;

  get mode(): PresenceMode {
    if (this.botSpeaking) return "speaking";
    if (this.userSpeaking) return "listening";
    return "idle";
  }
}
