/** The live trace. Renders MP-24's event stream verbatim.
 *
 *  Every line is a real event with a real timestamp and a real duration. Nothing here is
 *  scheduled or padded — if a stage took 4 ms the tape says 4 ms, which is less dramatic
 *  than a staged reveal and considerably more persuasive to anyone who has seen a staged one.
 */

import type { TraceEvent } from "../api/types";

function clockOf(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "--:--:--";
  return at.toTimeString().slice(0, 8);
}

export function TraceTape({
  events,
  traceId,
  running,
}: {
  events: TraceEvent[];
  traceId: string | null;
  running: boolean;
}) {
  return (
    <div className="fig">
      <div className="fig-head">
        <span>Trace</span>
        <b>MP-24</b>
        <span className="right">
          {traceId ? <span className="mono">{traceId}</span> : "awaiting run"}
        </span>
      </div>
      <div className="fig-body">
        {events.length === 0 ? (
          <p className="small">
            {running ? (
              <>
                <span className="spinner" /> running…
              </>
            ) : (
              "Run a verification and every pipeline stage will report here as it executes."
            )}
          </p>
        ) : (
          <div className="tape">
            {events.map((event) => (
              <div key={event.seq} className="tapeline" data-level={event.level}>
                <span className="k">{clockOf(event.at)}</span>
                <span className="v">
                  {event.message}
                  {event.module ? <span className="mod"> · {event.module}</span> : null}
                  {event.duration_ms !== null && event.duration_ms > 0 ? (
                    <span className="ms"> · {event.duration_ms} ms</span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      {events.length > 0 ? (
        <div className="fig-cap">
          Real timestamps from the pipeline, not an animation. A stage that did not run has no
          line here.
        </div>
      ) : null}
    </div>
  );
}
