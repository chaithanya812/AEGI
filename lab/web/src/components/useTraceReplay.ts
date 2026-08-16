import { useEffect, useRef, useState } from "react";

import type { TraceEvent } from "../api/types";

/** Reveals a completed trace one line at a time, using the events' **real** relative
 *  timings, compressed to fit a comfortable window.
 *
 *  Worth being precise about what is and is not real here, because the honesty of the trace
 *  is the whole point: every timestamp, module and duration on screen is exactly what the
 *  pipeline recorded. Only the *reveal pacing* is scaled — a 14-second run would otherwise
 *  scroll past in one frame, since the response arrives complete. The alternative, ticking
 *  lines out on a fixed timer while the request is still in flight, would be inventing
 *  progress the server has not reported, and that is the thing this product exists to
 *  object to.
 */
export function useTraceReplay(events: TraceEvent[], budgetMs = 2400) {
  const [shown, setShown] = useState<TraceEvent[]>([]);
  const [replaying, setReplaying] = useState(false);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];

    if (events.length === 0) {
      setShown([]);
      setReplaying(false);
      return;
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShown(events);
      setReplaying(false);
      return;
    }

    const first = new Date(events[0].at).getTime();
    const last = new Date(events[events.length - 1].at).getTime();
    const realSpan = Math.max(1, last - first);
    const scale = Math.min(1, budgetMs / realSpan);

    setShown([]);
    setReplaying(true);

    events.forEach((event, i) => {
      const offset = (new Date(event.at).getTime() - first) * scale;
      // A floor per line keeps consecutive sub-millisecond stages from landing together.
      const delay = Math.max(offset, i * 55);
      timers.current.push(
        window.setTimeout(() => {
          setShown((current) => [...current, event]);
          if (i === events.length - 1) setReplaying(false);
        }, delay),
      );
    });

    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [events, budgetMs]);

  return { shown, replaying };
}
