import Link from "next/link";

export default function HomePage() {
  return (
    <div className="relative mx-auto flex max-w-5xl flex-col items-center px-6 pb-32 pt-28 text-center sm:px-8 sm:pt-40">
      <p className="mb-6 text-xs uppercase tracking-widest2 text-gold/80">Autonomous software engineering</p>

      <h1 className="font-display text-balance text-5xl leading-[1.08] tracking-tightest text-ivory sm:text-6xl md:text-7xl">
        An agent that plans,
        <br />
        writes, tests, and <span className="italic text-gold">reviews</span>
        <br />
        its own work.
      </h1>

      <p className="mt-8 max-w-xl text-balance text-base leading-relaxed text-ivory-dim sm:text-lg">
        LocoPilot takes a task description and a repository, then runs a full engineering
        pipeline — orchestration, planning, implementation, testing, debugging, and review —
        with every step recorded and inspectable.
      </p>

      <div className="mt-11 flex flex-col items-center gap-4 sm:flex-row">
        <Link
          href="/dashboard"
          className="rounded-full bg-ivory px-7 py-3 text-sm font-medium tracking-wide text-ground transition-transform duration-200 hover:scale-[1.02]"
        >
          Open Dashboard
        </Link>
        <Link
          href="/executions"
          className="rounded-full border border-line-strong px-7 py-3 text-sm tracking-wide text-ivory-dim transition-colors duration-200 hover:border-gold/40 hover:text-ivory"
        >
          View Executions
        </Link>
      </div>

      <div className="mt-24 grid w-full grid-cols-1 gap-px overflow-hidden rounded-lg border border-line sm:grid-cols-3">
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
