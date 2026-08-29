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
    <div className="relative mx-auto flex max-w-6xl flex-col px-6 pb-24 pt-16 sm:px-8 sm:pt-20 lg:pt-24">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:gap-16">
        {/* Left: branding */}
        <div className="flex flex-col lg:pr-6">
          <p className="text-xs uppercase tracking-widest2 text-gold/80">{greeting}</p>
          <h1 className="mt-3 font-display text-balance text-5xl leading-[1.05] tracking-tightest text-ivory sm:text-6xl lg:text-7xl">
            Loco<span className="italic text-gold">Pilot</span>
          </h1>
          <p className="mt-5 font-display text-2xl leading-snug text-ivory-dim sm:text-3xl">
            Test. Debug. <span className="text-gold">Build.</span>
          </p>
          <p className="mt-4 max-w-md text-balance text-base leading-relaxed text-ivory-faint">
            An autonomous software-engineering agent — describe the task, and it plans, writes, tests, debugs, and
            reviews the change end to end.
          </p>

          <div className="mt-10 hidden gap-px overflow-hidden rounded-lg border border-line sm:grid sm:grid-cols-1 lg:grid">
            {PIPELINE_HIGHLIGHTS.map((item) => (
              <div key={item.title} className="bg-ground-raised/40 px-6 py-5 text-left transition-colors hover:bg-ground-raised/70">
                <p className="font-display text-lg text-ivory">{item.title}</p>
                <p className="mt-1 text-sm leading-relaxed text-ivory-faint">{item.body}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Right: command center — the primary interaction */}
        <div className="w-full lg:mt-0">
          <CommandCenter eyebrow="Command" heading="What should LocoPilot build?" placeholder="e.g. Add a power(a, b) function to calculator.py that raises a to the power of b, with a test." />
        </div>
      </div>

      <div className="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-line sm:grid-cols-3 lg:hidden">
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
