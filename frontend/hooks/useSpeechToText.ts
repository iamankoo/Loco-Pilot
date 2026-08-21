"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/** Minimal shape of the (non-standardized) Web Speech API this hook
 * needs — not present in TypeScript's DOM lib, so declared locally
 * rather than reaching for `any`. */
interface SpeechRecognitionResultLike {
  [index: number]: { transcript: string };
}
interface SpeechRecognitionEventLike {
  results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as SpeechRecognitionConstructor | null;
}

function subscribeNever() {
  return () => {};
}

export function useSpeechToText(onTranscript: (text: string) => void) {
  const [isListening, setIsListening] = useState(false);
  // Browser support never changes after mount, and differs between
  // SSR (no window) and the client — useSyncExternalStore reports the
  // safe default during hydration and the real value immediately after,
  // with no manual effect+setState round trip.
  const supported = useSyncExternalStore(
    subscribeNever,
    () => getSpeechRecognitionConstructor() !== null,
    () => false
  );
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
    };
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  const start = useCallback(() => {
    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) return;

    const recognition = new Recognition();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = Array.from({ length: event.results.length }, (_, i) => event.results[i]?.[0]?.transcript ?? "")
        .join(" ")
        .trim();
      if (transcript) onTranscript(transcript);
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [onTranscript]);

  const toggle = useCallback(() => {
    if (isListening) stop();
    else start();
  }, [isListening, start, stop]);

  return { isListening, supported, toggle };
}
