// Mirrors backend/app/avatar/protocol.py

export interface VisemeEvent {
  type: "viseme";
  utterance_id: number;
  mouth_open: number;
  // ARKit-named blendshape weights (0.0-1.0) from the backend's local spectral
  // viseme analysis (see backend/app/avatar/viseme_analysis.py).
  blendshapes?: Record<string, number>;
}

export interface PlaybackStartEvent {
  type: "playback_start";
  utterance_id: number;
}

export interface PlaybackEndEvent {
  type: "playback_end";
  utterance_id: number;
}

export interface InterruptEvent {
  type: "interrupt";
  utterance_id: number;
}

export type AvatarEvent = VisemeEvent | PlaybackStartEvent | PlaybackEndEvent | InterruptEvent;

export function isAvatarEvent(msg: unknown): msg is AvatarEvent {
  if (typeof msg !== "object" || msg === null) return false;
  const type = (msg as { type?: unknown }).type;
  return (
    type === "viseme" ||
    type === "playback_start" ||
    type === "playback_end" ||
    type === "interrupt"
  );
}
