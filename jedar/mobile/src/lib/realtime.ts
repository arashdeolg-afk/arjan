import { RTCPeerConnection, RTCSessionDescription, mediaDevices, type MediaStream } from "react-native-webrtc";
import { createRealtimeSession, type VoiceSelection } from "./api";
import { parseServerEvent, type SessionAction } from "./realtimeEvents";

type Dispatch = (action: SessionAction) => void;

const ICE_GATHER_TIMEOUT_MS = 2500;

/**
 * One live voice conversation over WebRTC. The SDP offer goes to the Jedar
 * server, never to OpenAI directly, and nothing here persists audio or text.
 */
export class RealtimeVoiceSession {
  private pc: RTCPeerConnection | null = null;
  private dc: ReturnType<RTCPeerConnection["createDataChannel"]> | null = null;
  private localStream: MediaStream | null = null;
  private remoteStreams: MediaStream[] = [];
  private ended = false;

  constructor(private readonly dispatch: Dispatch) {}

  async start(selection: VoiceSelection, installId: string): Promise<void> {
    this.ended = false;
    this.dispatch({ kind: "start" });
    try {
      const stream = await mediaDevices.getUserMedia({ audio: true, video: false });
      if (this.ended) {
        stopStream(stream);
        return;
      }
      this.localStream = stream;

      const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
      this.pc = pc;
      for (const track of stream.getTracks()) pc.addTrack(track, stream);

      pc.ontrack = (event: { streams: MediaStream[] }) => {
        for (const s of event.streams) if (!this.remoteStreams.includes(s)) this.remoteStreams.push(s);
      };
      pc.onconnectionstatechange = () => {
        const state = pc.connectionState;
        this.dispatch({ kind: "connection", state });
        if (state === "failed") this.dispatch({ kind: "error", message: "The voice connection was lost." });
      };

      const dc = pc.createDataChannel("oai-events");
      this.dc = dc;
      dc.onopen = () => this.dispatch({ kind: "connected" });
      dc.onmessage = (event: { data: unknown }) => {
        const parsed = parseServerEvent(event.data);
        if (parsed) this.dispatch({ kind: "server", event: parsed });
      };
      dc.onclose = () => {
        if (!this.ended) this.dispatch({ kind: "connection", state: "closed" });
      };

      const offer = await pc.createOffer({});
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
      const localSdp = pc.localDescription?.sdp;
      if (!localSdp) throw new Error("Could not create an offer");

      const answer = await createRealtimeSession(localSdp, selection, installId);
      if (this.ended) return;
      await pc.setRemoteDescription(new RTCSessionDescription({ type: "answer", sdp: answer }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not start the voice session";
      this.teardown();
      this.dispatch({ kind: "error", message });
      this.dispatch({ kind: "end" });
    }
  }

  /** Stop the microphone, remote audio, data channel and peer connection. Idempotent. */
  end(): void {
    if (this.ended) return;
    this.ended = true;
    this.teardown();
    this.dispatch({ kind: "end" });
  }

  private teardown(): void {
    try {
      this.dc?.close();
    } catch {
      // ignore
    }
    this.dc = null;
    if (this.localStream) {
      stopStream(this.localStream);
      this.localStream = null;
    }
    for (const s of this.remoteStreams) stopStream(s);
    this.remoteStreams = [];
    try {
      this.pc?.close();
    } catch {
      // ignore
    }
    this.pc = null;
  }
}

function stopStream(stream: MediaStream): void {
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch {
      // ignore
    }
  }
}

function waitForIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(done, ICE_GATHER_TIMEOUT_MS);
    function done() {
      clearTimeout(timer);
      pc.onicegatheringstatechange = null;
      resolve();
    }
    pc.onicegatheringstatechange = () => {
      if (pc.iceGatheringState === "complete") done();
    };
  });
}
