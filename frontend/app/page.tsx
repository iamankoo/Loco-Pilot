"use client";

import { useSyncExternalStore } from "react";
import { CommandCenter } from "@/features/dashboard/CommandCenter";

function timeOfDayGreeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function subscribeNever() {
  return () => {};
}

export default function HomePage() {
  // The greeting reflects the visitor's own clock, which the server can't
  // know — useSyncExternalStore renders a neutral value during SSR/initial
  // hydration, then the real one immediately after, without a manual
  // effect+setState round trip.
  const greeting = useSyncExternalStore(
    subscribeNever,
    () => timeOfDayGreeting(new Date().getHours()),
    () => "Hello"
  );

  return (
    <div className="relative mx-auto flex max-w-3xl flex-col items-center px-6 pb-32 pt-24 text-center sm:px-8 sm:pt-32">
      <h1 className="font-display text-balance text-4xl leading-[1.15] tracking-tightest text-ivory sm:text-5xl">
        {greeting}, <span className="italic text-gold">champ</span>.
      </h1>
      <p className="mt-3 text-balance text-lg text-ivory-dim">What should we build today?</p>
      <p className="mt-1 text-sm text-ivory-faint">Turn your idea into working code.</p>

      <div className="mt-10 w-full text-left">
        <CommandCenter eyebrow="" heading="" placeholder="Tell LocoPilot what you want to build…" />
      </div>

      <div className="mt-20 grid w-full grid-cols-1 gap-px overflow-hidden rounded-lg border border-line sm:grid-cols-3">
        {PIPELINE_HIGHLIGHTS.map((item) => (
          <div key={item.title} className="bg-ground-raised/40 px-7 py-8 text-left">
            <p className="font-display text-xl text-ivory">{item.title}</p>
            <p className="mt-2 text-base leading-relaxed text-ivory-faint">{item.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

const PIPELINE_HIGHLIGHTS = [
  {
    title: "Full pipeline visibility",
    body: "Every agent turn, tool call, and test run is persisted and streamed live — no hidden reasoning, no black box.",
  },
  {
    title: "Bounded autonomy",
    body: "Retry loops, tool budgets, and execution timeouts keep every run predictable and cancellable.",
  },
  {
    title: "Real diffs, real tests",
    body: "Changes are made and verified inside an isolated sandbox, with actual test output — never fabricated results.",
  },
];
