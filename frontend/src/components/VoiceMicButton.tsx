/**
 * VoiceMicButton.tsx
 *
 * Renders a mic button that:
 *  1. Records audio via MediaRecorder (webm/opus).
 *  2. POSTs the blob to /voice/transcribe (Groq Whisper).
 *  3. Fires onTranscribed(result) — the parent decides routing.
 *  4. Accepts a `speakText` prop so the parent can trigger TTS at the
 *     right moment (after the AI response is ready), using Web Speech API.
 *
 * Exported helper: speakResponse(text) — call this after you have the
 *   final AI response text to read it aloud.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import type { TranscribeResponse } from "../types";
import { transcribeAudio } from "../api";

// ── Web Speech API TTS helper ─────────────────────────────────────────────────

export function speakResponse(text: string, rate = 1.0, pitch = 1.0): void {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel(); // stop any in-progress speech
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = rate;
  utterance.pitch = pitch;
  utterance.lang = "en-US";
  // Prefer a natural-sounding voice when available
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find(
    (v) =>
      v.lang.startsWith("en") &&
      (v.name.toLowerCase().includes("natural") ||
        v.name.toLowerCase().includes("neural") ||
        v.name.toLowerCase().includes("google"))
  );
  if (preferred) utterance.voice = preferred;
  window.speechSynthesis.speak(utterance);
}

// ── Types ─────────────────────────────────────────────────────────────────────

type RecordingState = "idle" | "recording" | "transcribing" | "error";

export interface VoiceMicButtonProps {
  /** Called with the full transcription result after Whisper + intent pass */
  onTranscribed: (result: TranscribeResponse) => void;
  /** Whether the button should be disabled (e.g., while the AI is streaming) */
  disabled?: boolean;
  /** Size variant */
  size?: "sm" | "md";
  /** Style variant */
  variant?: "solid" | "ghost";
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function VoiceMicButton({
  onTranscribed,
  disabled = false,
  size = "md",
  variant = "solid",
}: VoiceMicButtonProps) {
  const [state, setState] = useState<RecordingState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [level, setLevel] = useState(0); // 0–1 audio level for pulse animation

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);
  const streamRef = useRef<MediaStream | null>(null);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopAnimationLoop();
      stopStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopStream() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  function stopAnimationLoop() {
    cancelAnimationFrame(animFrameRef.current);
  }

  function startLevelMonitor(stream: MediaStream) {
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyserRef.current = analyser;

    const buf = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(buf);
      const avg = buf.reduce((s, v) => s + v, 0) / buf.length;
      setLevel(Math.min(avg / 80, 1));
      animFrameRef.current = requestAnimationFrame(tick);
    };
    animFrameRef.current = requestAnimationFrame(tick);
  }

  const startRecording = useCallback(async () => {
    setErrorMsg(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      startLevelMonitor(stream);

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "audio/ogg";

      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stopAnimationLoop();
        stopStream();
        setLevel(0);

        const blob = new Blob(chunksRef.current, { type: mimeType });
        const ext = mimeType.includes("ogg") ? "ogg" : "webm";
        setState("transcribing");

        try {
          const result = await transcribeAudio(blob, `audio.${ext}`);
          setState("idle");
          onTranscribed(result);
        } catch (err: unknown) {
          setState("error");
          setErrorMsg(err instanceof Error ? err.message : "Transcription failed");
          setTimeout(() => setState("idle"), 3500);
        }
      };

      recorder.start(250); // collect in 250 ms chunks
      setState("recording");
    } catch (err: unknown) {
      setState("error");
      setErrorMsg(
        err instanceof Error && err.name === "NotAllowedError"
          ? "Microphone access denied — please allow it in your browser."
          : "Could not access microphone."
      );
      setTimeout(() => setState("idle"), 3500);
    }
  }, [onTranscribed]);

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop();
  }, []);

  const handleClick = useCallback(() => {
    if (state === "recording") {
      stopRecording();
    } else if (state === "idle") {
      startRecording();
    }
  }, [state, startRecording, stopRecording]);

  // ── Derived styles ──────────────────────────────────────────────────────────

  const isSmall = size === "sm";
  const btnSize = isSmall ? "p-2" : "p-2.5";
  const iconSize = isSmall ? "w-4 h-4" : "w-5 h-5";

  const pulseScale = 1 + level * 0.35;

  const baseClasses = [
    btnSize,
    "relative rounded-lg transition-all duration-150 flex items-center justify-center shrink-0 select-none",
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
  ].join(" ");

  const stateClasses: Record<RecordingState, string> = variant === "ghost" ? {
    idle: "bg-transparent hover:bg-[#333333] text-gray-400 hover:text-gray-200",
    recording: "bg-red-500/20 text-red-400 ring-1 ring-red-500/50",
    transcribing: "bg-transparent text-gray-500 cursor-wait",
    error: "bg-red-900/30 text-red-400 cursor-default",
  } : {
    idle: "bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white",
    recording: "bg-red-600 hover:bg-red-500 text-white",
    transcribing: "bg-gray-700 text-gray-400 cursor-wait",
    error: "bg-red-900/50 text-red-400 cursor-default",
  };

  const isDisabled = disabled || state === "transcribing";

  return (
    <div className="relative flex flex-col items-center">
      <button
        id="voice-mic-btn"
        type="button"
        aria-label={
          state === "recording"
            ? "Stop recording"
            : state === "transcribing"
            ? "Transcribing…"
            : "Record voice command"
        }
        aria-pressed={state === "recording"}
        onClick={handleClick}
        disabled={isDisabled}
        className={`${baseClasses} ${stateClasses[state]} disabled:opacity-50 disabled:cursor-not-allowed`}
        style={
          state === "recording"
            ? { transform: `scale(${pulseScale})`, transition: "transform 0.1s ease" }
            : undefined
        }
      >
        {/* Ripple ring when recording */}
        {state === "recording" && (
          <span
            className="absolute inset-0 rounded-lg ring-2 ring-red-500 animate-ping opacity-60 pointer-events-none"
            style={{ animationDuration: "1.2s" }}
          />
        )}

        {/* Icon */}
        {state === "transcribing" ? (
          // Spinner
          <svg
            className={`${iconSize} animate-spin`}
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v8H4z"
            />
          </svg>
        ) : state === "recording" ? (
          // Square = stop
          <svg
            className={iconSize}
            viewBox="0 0 24 24"
            fill="currentColor"
          >
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        ) : (
          // Mic
          <svg
            className={iconSize}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
        )}
      </button>

      {/* Error tooltip */}
      {errorMsg && (
        <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-56 text-center bg-red-950 border border-red-800 text-red-300 text-xs rounded-lg px-3 py-2 shadow-xl pointer-events-none z-50">
          {errorMsg}
        </div>
      )}
    </div>
  );
}
