import { WebSocketTransport } from "@pipecat-ai/websocket-transport";
import {
  Participant,
  PipecatClient,
  PipecatClientOptions,
  TransportState,
} from "@pipecat-ai/client-js";

import { createScene } from "./avatar/scene";
import { loadAvatar } from "./avatar/avatarLoader";
import { ArmGestures } from "./avatar/armGestures";
import { BlendshapeCompositor } from "./avatar/blendshapeCompositor";
import { BodyAnimator } from "./avatar/bodyAnimator";
import { IdleFace } from "./avatar/idleFace";
import { AvatarPresence } from "./avatar/presence";
import { VisemeDriver } from "./avatar/visemeDriver";
import { isAvatarEvent } from "./protocol/avatarProtocol";

const BASE_URL = (import.meta as any).env?.VITE_PIPECAT_BASE_URL || "http://localhost:7860";

const canvas = document.getElementById("scene") as HTMLCanvasElement;
const connectBtn = document.getElementById("connect-btn") as HTMLButtonElement;
const disconnectBtn = document.getElementById("disconnect-btn") as HTMLButtonElement;
const statusSpan = document.getElementById("connection-status") as HTMLElement;
const debugLog = document.getElementById("debug-log") as HTMLElement;
const botAudio = document.getElementById("bot-audio") as HTMLAudioElement;

function log(message: string) {
  const entry = document.createElement("div");
  entry.textContent = `${new Date().toISOString()} - ${message}`;
  debugLog.appendChild(entry);
  debugLog.scrollTop = debugLog.scrollHeight;
}

function setStatus(status: string) {
  statusSpan.textContent = status;
  log(`Status: ${status}`);
}

const sceneHandle = createScene(canvas);
const presence = new AvatarPresence();
const compositor = new BlendshapeCompositor();
const visemeDriver = new VisemeDriver(presence, compositor);
const idleFace = new IdleFace(presence, compositor);
const bodyAnimator = new BodyAnimator(presence);
const armGestures = new ArmGestures(presence);

loadAvatar(sceneHandle.scene).then((avatar) => {
  compositor.setAvatar(avatar);
  // After loadAvatar, so the rest poses captured include its arms-down posing.
  bodyAnimator.setAvatar(avatar);
  armGestures.setAvatar(avatar);
});

sceneHandle.onTick((delta) => {
  // Layers publish their weights first, then the compositor is the single
  // writer to the mesh's morph targets.
  visemeDriver.update(delta);
  idleFace.update(delta);
  compositor.apply();
  // Body before arms: the arm swing is computed in world space and reads the
  // spine/shoulder transforms this frame already produced.
  bodyAnimator.update(delta);
  armGestures.update(delta);
});

const options: PipecatClientOptions = {
  transport: new WebSocketTransport(),
  enableMic: true,
  enableCam: false,
  callbacks: {
    onTransportStateChanged: (state: TransportState) => log(`Transport state: ${state}`),
    onConnected: () => {
      setStatus("Connected");
      connectBtn.disabled = true;
      disconnectBtn.disabled = false;
    },
    onBotReady: () => log("Bot is ready."),
    onDisconnected: () => {
      setStatus("Disconnected");
      presence.botSpeaking = false;
      presence.userSpeaking = false;
      connectBtn.disabled = false;
      disconnectBtn.disabled = true;
    },
    onUserStartedSpeaking: () => {
      log("User started speaking.");
      presence.userSpeaking = true;
    },
    onUserStoppedSpeaking: () => {
      log("User stopped speaking.");
      presence.userSpeaking = false;
    },
    onBotStartedSpeaking: () => {
      log("Bot started speaking.");
      presence.botSpeaking = true;
    },
    onBotStoppedSpeaking: () => {
      log("Bot stopped speaking.");
      presence.botSpeaking = false;
    },
    onTrackStarted: (track: MediaStreamTrack, participant?: Participant) => {
      // Note: @pipecat-ai/websocket-transport never actually fires this for bot
      // audio (it plays through an internal player, not a MediaStreamTrack) --
      // this only matters if the WebRTC transport is swapped in later.
      if (participant?.local || track.kind !== "audio") return;
      botAudio.srcObject = new MediaStream([track]);
    },
    onServerMessage: (msg: unknown) => {
      if (isAvatarEvent(msg)) {
        visemeDriver.handleAvatarEvent(msg);
      } else {
        log(`Server message: ${JSON.stringify(msg)}`);
      }
    },
  },
};

const client = new PipecatClient(options);

async function connect() {
  await client.initDevices();
  connectBtn.disabled = true;
  try {
    setStatus("Starting the bot");
    const startResult = await client.startBot({
      endpoint: `${BASE_URL}/start`,
      requestData: { transport: "websocket" },
    });
    const wsUrl = (startResult as { wsUrl: string }).wsUrl;
    await client.connect({ wsUrl });
  } catch (err) {
    console.error("Failed to connect", err);
    connectBtn.disabled = false;
  }
}

function disconnect() {
  void client.disconnect();
}

connectBtn.addEventListener("click", connect);
disconnectBtn.addEventListener("click", disconnect);
