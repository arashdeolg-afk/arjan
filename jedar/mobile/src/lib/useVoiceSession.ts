import { useCallback, useEffect, useReducer, useRef } from "react";
import { RealtimeVoiceSession } from "./realtime";
import { INITIAL_STATE, reduceSession, type SessionState } from "./realtimeEvents";
import { sendTextMessage, type VoiceSelection } from "./api";

/** Owns one RealtimeVoiceSession and guarantees teardown on unmount. */
export function useVoiceSession(installId: string) {
  const [state, dispatch] = useReducer(reduceSession, INITIAL_STATE);
  const sessionRef = useRef<RealtimeVoiceSession | null>(null);
  const stateRef = useRef<SessionState>(state);
  stateRef.current = state;

  const end = useCallback(() => {
    sessionRef.current?.end();
    sessionRef.current = null;
  }, []);

  const start = useCallback(
    async (selection: VoiceSelection) => {
      end();
      const session = new RealtimeVoiceSession(dispatch);
      sessionRef.current = session;
      await session.start(selection, installId);
    },
    [end, installId],
  );

  const sendText = useCallback(
    async (text: string, selection: VoiceSelection) => {
      const id = `t-${Date.now()}`;
      dispatch({ kind: "text.user", id, text });
      const history = stateRef.current.transcript
        .filter((e) => e.final && e.text.trim())
        .slice(-20)
        .map((e) => ({ role: e.role, content: e.text }));
      try {
        const reply = await sendTextMessage({ message: text, faith: selection.faith, mode: selection.mode, reflectionId: selection.reflectionId, history }, installId);
        dispatch({ kind: "text.assistant", id: `${id}-reply`, text: reply });
      } catch (err) {
        dispatch({ kind: "error", message: err instanceof Error ? err.message : "Jedar could not reply right now" });
      }
    },
    [installId],
  );

  const clear = useCallback(() => dispatch({ kind: "clear" }), []);

  useEffect(() => end, [end]);

  return { state, start, end, sendText, clear };
}
