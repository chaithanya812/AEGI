import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "./api/client";
import type {
  CorpusDoc,
  CorpusSummary,
  Health,
  LogRow,
  Persistence,
  Preset,
  RunResult,
} from "./api/types";
import { PipelineGraph } from "./components/PipelineGraph";
import { TraceTape } from "./components/TraceTape";
import { VerdictPanel } from "./components/VerdictPanel";
import { useTraceReplay } from "./components/useTraceReplay";

type Page = "lab" | "corpus" | "log" | "method";

const PAGES: Array<{ id: Page; num: string; label: string }> = [
  { id: "lab", num: "01", label: "Lab" },
  { id: "corpus", num: "02", label: "Corpus" },
  { id: "log", num: "03", label: "Audit log" },
  { id: "method", num: "04", label: "Method" },
];

/** The other three tabs from the plan, present so the shape of the product is legible and
 *  turning one on later is a route plus a component. Disabled rather than hidden: a client
 *  should see what is deliberately not built yet. */
const PLANNED = ["Fine-tune", "Geo change", "Sheets"];

const LAYER_LABELS: Array<[string, string, string]> = [
  ["retrieval", "Retrieval", "MP-06/44"],
  ["temporal", "Temporal", "MP-12"],
  ["citation", "Citation", "MP-11"],
  ["contradiction", "Contradiction", "MP-10"],
  ["judge", "Entailment", "MP-09"],
];

const DOMAINS = ["general", "financial", "legal", "clinical"];

export default function App() {
  const [page, setPage] = useState<Page>("lab");
  const [health, setHealth] = useState<Health | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);

  const [text, setText] = useState("");
  const [mode, setMode] = useState<"generate" | "verify_given">("verify_given");
  const [domain, setDomain] = useState("general");
  const [layers, setLayers] = useState<Record<string, boolean>>({
    retrieval: true,
    temporal: true,
    citation: true,
    contradiction: true,
    judge: true,
  });
  const [activePreset, setActivePreset] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunResult[]>([]);
  const [persistence, setPersistence] = useState<Persistence[]>([]);
  const [selected, setSelected] = useState(0);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.health(), api.presets()])
      .then(([h, p]) => {
        setHealth(h);
        setPresets(p.presets);
      })
      .catch((error: ApiError) => setBootError(error.message));
  }, []);

  const selectedRun = runs[selected] ?? null;
  const { shown: tapeEvents, replaying } = useTraceReplay(selectedRun?.events ?? []);

  const lines = useMemo(
    () => text.split("\n").map((l) => l.trim()).filter(Boolean),
    [text],
  );

  const run = useCallback(async () => {
    setRunError(null);
    setRunning(true);
    setRuns([]);
    setPersistence([]);
    setSelected(0);
    try {
      const response =
        mode === "generate"
          ? await api.generate({ prompt: text.trim(), layers, domain })
          : await api.verify({ outputs: lines, layers, domain });
      setRuns(response.runs);
      setPersistence(response.persistence);
    } catch (error) {
      setRunError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setRunning(false);
    }
  }, [mode, text, lines, layers, domain]);

  const applyPreset = useCallback((preset: Preset) => {
    setActivePreset(preset.id);
    setMode(preset.mode);
    setDomain(preset.domain);
    setText(preset.mode === "generate" ? (preset.prompt ?? "") : (preset.text ?? ""));
    setRuns([]);
    setRunError(null);
  }, []);

  const canRun = !running && (mode === "generate" ? text.trim().length > 0 : lines.length > 0);

  const counters = useMemo(() => {
    const flagged = runs.filter((r) => r.reliability.band !== "VERIFIED").length;
    const wrong = runs.filter((r) => r.reliability.band === "UNRELIABLE").length;
    return { checked: runs.length, flagged, wrong };
  }, [runs]);

  const loggedFor = (traceId: string) => persistence.find((p) => p.trace_id === traceId);

  return (
    <>
      <header className="topbar">
        <div className="wrap topbar-in">
          <div className="brand">
            <span className="n">AI Reliability Lab</span>
            <span className="s">Don&rsquo;t just generate. Verify.</span>
          </div>
          <nav className="tabs" aria-label="Sections">
            {PAGES.map((p) => (
              <button
                key={p.id}
                className="tab"
                type="button"
                aria-current={page === p.id ? "page" : undefined}
                onClick={() => setPage(p.id)}
              >
                <span className="num">{p.num}</span> {p.label}
              </button>
            ))}
            {PLANNED.map((label) => (
              // aria-label rather than title: a title attribute becomes the accessible name
              // and would make all three of these announce identically.
              <button
                key={label}
                className="tab"
                type="button"
                disabled
                aria-label={`${label} — planned, not built in v1`}
              >
                <span className="num">··</span> {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="wrap">
        {bootError ? (
          <div className="section">
            <div className="notice">
              <span className="tag">Offline</span>
              <span>
                The verification service is not reachable: {bootError}. Start it with{" "}
                <span className="mono">uvicorn app.main:app --reload</span> from the{" "}
                <span className="mono">lab/</span> directory.
              </span>
            </div>
          </div>
        ) : null}

        {page === "lab" ? (
          <LabPage
            health={health}
            presets={presets}
            activePreset={activePreset}
            applyPreset={applyPreset}
            text={text}
            setText={setText}
            mode={mode}
            setMode={setMode}
            domain={domain}
            setDomain={setDomain}
            layers={layers}
            setLayers={setLayers}
            lines={lines}
            canRun={canRun}
            running={running}
            replaying={replaying}
            onRun={run}
            runs={runs}
            selected={selected}
            setSelected={setSelected}
            runError={runError}
            tapeEvents={tapeEvents}
            selectedRun={selectedRun}
            counters={counters}
            loggedFor={loggedFor}
          />
        ) : null}

        {page === "corpus" ? <CorpusPage /> : null}
        {page === "log" ? <LogPage /> : null}
        {page === "method" ? <MethodPage health={health} /> : null}
      </main>

      <footer className="wrap foot">
        <span>AI Reliability Lab · pipeline {health?.pipeline_version ?? "—"}</span>
        <span>
          {health?.model.configured ? health.model.model_id : "no model configured"} ·{" "}
          {health?.corpus.retrieval ?? "corpus not loaded"}
        </span>
        <span className="right">
          signing {health?.signing.key_id ?? "—"}
          {health?.signing.ephemeral ? " (ephemeral)" : ""}
        </span>
      </footer>
    </>
  );
}

// --- lab ---------------------------------------------------------------------

interface LabProps {
  health: Health | null;
  presets: Preset[];
  activePreset: string | null;
  applyPreset: (p: Preset) => void;
  text: string;
  setText: (v: string) => void;
  mode: "generate" | "verify_given";
  setMode: (v: "generate" | "verify_given") => void;
  domain: string;
  setDomain: (v: string) => void;
  layers: Record<string, boolean>;
  setLayers: (v: Record<string, boolean>) => void;
  lines: string[];
  canRun: boolean;
  running: boolean;
  replaying: boolean;
  onRun: () => void;
  runs: RunResult[];
  selected: number;
  setSelected: (i: number) => void;
  runError: string | null;
  tapeEvents: RunResult["events"];
  selectedRun: RunResult | null;
  counters: { checked: number; flagged: number; wrong: number };
  loggedFor: (traceId: string) => Persistence | undefined;
}

function LabPage(props: LabProps) {
  const {
    health,
    presets,
    activePreset,
    applyPreset,
    text,
    setText,
    mode,
    setMode,
    domain,
    setDomain,
    layers,
    setLayers,
    lines,
    canRun,
    running,
    replaying,
    onRun,
    runs,
    selected,
    setSelected,
    runError,
    tapeEvents,
    selectedRun,
    counters,
    loggedFor,
  } = props;

  const preset = presets.find((p) => p.id === activePreset) ?? null;
  const offLayers = Object.entries(layers).filter(([, on]) => !on).map(([k]) => k);

  return (
    <>
      <div className="titleblock">
        <h1>Every sentence checked against evidence, then signed.</h1>
        <div className="meta">
          <span>
            Sheet <b>01</b>
          </span>
          <span>Lab</span>
          <span>
            Rev <b>{health?.pipeline_version ?? "—"}</b>
          </span>
        </div>
      </div>

      <section className="section">
        <p className="lede col">
          Paste model output — one per line, one tile each — or give a prompt and let the lab
          generate first. Each sentence is broken into individually checkable claims, each claim
          is checked against a fixed evidence corpus, and the verdict is signed so it can be
          proved later.
        </p>

        <div className="labgrid">
          <div className="stack">
            <div className="fig">
              <div className="fig-head">
                <span>Input</span>
                <b>{mode === "generate" ? "prompt → generate → verify" : "verify as given"}</b>
                <span className="right">
                  {mode === "generate" ? "1 output" : `${lines.length} output(s)`}
                </span>
              </div>
              <div className="fig-body stack">
                <div className="chipset">
                  <button
                    className="chipbtn"
                    type="button"
                    aria-pressed={mode === "verify_given"}
                    onClick={() => setMode("verify_given")}
                  >
                    Verify pasted text
                  </button>
                  <button
                    className="chipbtn"
                    type="button"
                    aria-pressed={mode === "generate"}
                    onClick={() => setMode("generate")}
                    disabled={!health?.model.configured}
                    title={health?.model.configured ? undefined : "No model key configured"}
                  >
                    Ask the model first
                  </button>
                </div>

                <textarea
                  className="input"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    mode === "generate"
                      ? "Who won the 2027 FIFA World Cup?"
                      : "The Eiffel Tower was built in 1789 by Napoleon Bonaparte…\nOne output per line."
                  }
                  spellCheck={false}
                />

                <div className="chipset">
                  <button className="btn" type="button" onClick={onRun} disabled={!canRun}>
                    {running ? (
                      <>
                        <span className="spinner" /> running
                      </>
                    ) : (
                      "Run verification →"
                    )}
                  </button>
                  {DOMAINS.map((d) => (
                    <button
                      key={d}
                      className="chipbtn"
                      type="button"
                      aria-pressed={domain === d}
                      onClick={() => setDomain(d)}
                      aria-label={`Domain sensitivity: ${d}`}
                    >
                      {d}
                    </button>
                  ))}
                </div>

                <p className="small">
                  Domain sets MP-14&rsquo;s sensitivity multiplier. One unsupported claim in a
                  meeting summary is MEDIUM risk; the identical claim in a dosage recommendation
                  is CRITICAL. Same reliability report, different decision.
                </p>
              </div>
            </div>

            <div className="fig">
              <div className="fig-head">
                <span>Rehearsed cases</span>
                <b>{presets.length}</b>
                <span className="right">then type anything you like</span>
              </div>
              <div className="fig-body stack">
                <div className="chipset">
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      className="chipbtn"
                      type="button"
                      aria-pressed={activePreset === p.id}
                      onClick={() => applyPreset(p)}
                    >
                      <span className="dotmark" data-tone={p.tone} />
                      {p.label}
                    </button>
                  ))}
                </div>
                {preset ? (
                  <>
                    <p className="small">
                      <b>Expected:</b> {preset.expect}
                    </p>
                    <p className="small">
                      <b>What guarantees it:</b> {preset.carried_by}
                    </p>
                  </>
                ) : (
                  <p className="small">
                    Each rehearsed case is carried by a check that cannot fail — date
                    arithmetic, or a figure in a document we wrote. Nothing here depends on the
                    model cooperating, which is why the unrehearsed box above is safe to hand
                    over.
                  </p>
                )}
              </div>
            </div>

            <div className="fig">
              <div className="fig-head">
                <span>The rig</span>
                <b>switch a validator off</b>
                <span className="right">{offLayers.length === 0 ? "all on" : `${offLayers.length} off`}</span>
              </div>
              <div className="fig-body stack">
                <div className="chipset">
                  {LAYER_LABELS.map(([key, label, module]) => (
                    <button
                      key={key}
                      className="chipbtn"
                      type="button"
                      aria-pressed={layers[key]}
                      onClick={() => setLayers({ ...layers, [key]: !layers[key] })}
                      aria-label={`${label} validator (${module}), ${layers[key] ? "on" : "off"}`}
                    >
                      {label} <span style={{ opacity: 0.55 }}>{module}</span>
                    </button>
                  ))}
                </div>
                <p className="small">
                  Turn the citation validator off, run the same input again, and watch the bad
                  figure sail through. The certificate records which validators were on, so a
                  verdict produced with one disabled is never indistinguishable from a full run.
                </p>
              </div>
            </div>
          </div>

          <div className="stack">
            <div className="fig">
              <div className="fig-head">
                <span>Pipeline</span>
                <b>lights as it runs</b>
              </div>
              <div className="fig-body">
                <PipelineGraph events={tapeEvents} running={replaying} layers={layers} />
              </div>
            </div>
            <TraceTape
              events={tapeEvents}
              traceId={selectedRun?.trace_id ?? null}
              running={running || replaying}
            />
          </div>
        </div>
      </section>

      {runError ? (
        <section className="section">
          <div className="notice">
            <span className="tag">Failed</span>
            <span>{runError}</span>
          </div>
        </section>
      ) : null}

      {runs.length > 0 ? (
        <section className="section">
          <div className="rule-label">Results</div>

          <div className="legend">
            <span>
              <i data-band="VERIFIED" /> verified — passed clean
            </span>
            <span>
              <i data-band="QUALIFIED" /> qualified — flagged, not guessed
            </span>
            <span>
              <i data-band="UNRELIABLE" /> unreliable — caught
            </span>
          </div>

          <div className="tiles">
            {runs.map((r, i) => (
              <button
                key={r.trace_id}
                className="tile"
                type="button"
                data-band={r.reliability.band}
                aria-pressed={selected === i}
                onClick={() => setSelected(i)}
                title={`${r.reliability.band} · ${r.reliability.score} · ${r.decision.outcome}`}
              >
                {r.reliability.score}
              </button>
            ))}
          </div>

          <p className="counters">
            <b>{counters.checked}</b> checked · <b>{counters.flagged}</b> flagged ·{" "}
            <span className="bad">{counters.wrong} unreliable</span> · click any tile to see what
            the validator read
          </p>

          {selectedRun ? (
            <VerdictPanel
              run={selectedRun}
              logged={loggedFor(selectedRun.trace_id)?.logged ?? false}
              logError={loggedFor(selectedRun.trace_id)?.error ?? null}
            />
          ) : null}
        </section>
      ) : null}
    </>
  );
}

// --- corpus ------------------------------------------------------------------

function CorpusPage() {
  const [summary, setSummary] = useState<CorpusSummary | null>(null);
  const [docs, setDocs] = useState<CorpusDoc[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .corpus()
      .then((r) => {
        setSummary(r.summary);
        setDocs(r.documents);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  return (
    <>
      <div className="titleblock">
        <h1>What the lab is allowed to check against.</h1>
        <div className="meta">
          <span>
            Sheet <b>02</b>
          </span>
          <span>Corpus</span>
        </div>
      </div>

      <section className="section">
        <p className="lede col">
          Shown in full, on purpose. A verifier that will not tell you the extent of its
          evidence is asking for blind trust — and the honest limit of this lab is exactly
          these documents. Anything outside them comes back <b>unknown</b>, never
          &ldquo;wrong&rdquo;.
        </p>

        {error ? (
          <div className="notice">
            <span className="tag">Error</span>
            <span>{error}</span>
          </div>
        ) : null}

        {summary ? (
          <p className="small">
            {summary.documents} documents · {summary.chunks} chunks · retrieval:{" "}
            <b>{summary.retrieval}</b>
            {summary.embed_model ? ` · ${summary.embed_model} @ ${summary.embed_dims}d` : ""}
          </p>
        ) : null}

        <div className="fig">
          <div className="fig-head">
            <span>Table 01</span>
            <b>Indexed documents</b>
            <span className="right">reference = public facts · matter = the customer&rsquo;s own</span>
          </div>
          <div className="fig-body scroller">
            <table className="tbl" style={{ minWidth: "52rem" }}>
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">Title</th>
                  <th scope="col">Collection</th>
                  <th scope="col">Authority</th>
                  <th scope="col">Effective</th>
                  <th scope="col">Supersedes</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.doc_id}>
                    <td className="k">{d.doc_id}</td>
                    <td>{d.title}</td>
                    <td className="k">{d.collection}</td>
                    <td className="k">
                      {d.authority.toFixed(2)} · {d.authority_tier || "—"}
                    </td>
                    <td className="k">{d.effective_date ?? "—"}</td>
                    <td className="k">{d.supersedes ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="fig-cap">
            Authority tiers are configuration, not truth: an audited account outranks the same
            company&rsquo;s press release, and a superseding amendment outranks the agreement it
            amends regardless of tier. In a real deployment these are the customer&rsquo;s own
            document stores, connected at ingest with their permissions attached.
          </div>
        </div>
      </section>
    </>
  );
}

// --- audit log ---------------------------------------------------------------

function LogPage() {
  const [rows, setRows] = useState<LogRow[]>([]);
  const [counters, setCounters] = useState<Record<string, number>>({});
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [traceId, setTraceId] = useState("");
  const [replayed, setReplayed] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .log(60)
      .then((r) => {
        setEnabled(r.enabled);
        setRows(r.runs);
        setCounters(r.counters);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const replay = useCallback(async (id: string) => {
    setReplayed(null);
    setError(null);
    try {
      const row = await api.trace(id.trim());
      setReplayed(JSON.stringify(row, null, 2));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  return (
    <>
      <div className="titleblock">
        <h1>Every verdict, retrievable months later.</h1>
        <div className="meta">
          <span>
            Sheet <b>03</b>
          </span>
          <span>Audit log</span>
          <span>
            MP-<b>24</b>
          </span>
        </div>
      </div>

      <section className="section">
        <p className="lede col">
          Each run writes the request, every extracted claim with its verdict and evidence, the
          full event trail, and the signed certificate. This is what turns &ldquo;the AI said
          so&rdquo; into a record that survives a regulator asking about one specific answer from
          eight months ago.
        </p>

        {!enabled ? (
          <div className="notice" data-soft="true">
            <span className="tag">Not configured</span>
            <span>
              The audit log has no database configured, so runs are not being stored. Verdicts
              are still signed — the certificate is self-contained by design and verifies
              without this log.
            </span>
          </div>
        ) : null}

        {error ? (
          <div className="notice">
            <span className="tag">Error</span>
            <span>{error}</span>
          </div>
        ) : null}

        {enabled ? (
          <>
            <p className="small">
              {counters.total ?? 0} runs logged · {counters.unreliable ?? 0} unreliable ·{" "}
              {counters.false_certainty ?? 0} with false certainty
            </p>

            <div className="chipset">
              <input
                className="input"
                style={{ minHeight: "auto", maxWidth: "18rem", fontFamily: "var(--mono)" }}
                placeholder="trace_… "
                value={traceId}
                onChange={(e) => setTraceId(e.target.value)}
              />
              <button
                className="btn ghost"
                type="button"
                onClick={() => replay(traceId)}
                disabled={!traceId.trim()}
              >
                Replay by trace id
              </button>
              <button className="btn ghost" type="button" onClick={load}>
                Refresh
              </button>
            </div>

            {replayed ? (
              <div className="fig">
                <div className="fig-head">
                  <span>Replayed from the log</span>
                  <b>as stored</b>
                </div>
                <div className="fig-body">
                  <pre
                    className="mono"
                    style={{ fontSize: "0.72rem", maxHeight: "26rem", overflow: "auto", margin: 0 }}
                  >
                    {replayed}
                  </pre>
                </div>
              </div>
            ) : null}

            <div className="fig">
              <div className="fig-head">
                <span>Table 01</span>
                <b>Recent runs</b>
                <span className="right">{rows.length} shown</span>
              </div>
              <div className="fig-body scroller">
                <table className="tbl" style={{ minWidth: "52rem" }}>
                  <thead>
                    <tr>
                      <th scope="col">Trace</th>
                      <th scope="col">When</th>
                      <th scope="col">Output</th>
                      <th scope="col">Band</th>
                      <th scope="col">Decision</th>
                      <th scope="col">Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.trace_id}>
                        <td className="k">
                          <button
                            className="btn tiny ghost"
                            type="button"
                            onClick={() => {
                              setTraceId(r.trace_id);
                              replay(r.trace_id);
                            }}
                          >
                            {r.trace_id}
                          </button>
                        </td>
                        <td className="k">{r.created_at?.slice(0, 19).replace("T", " ")}</td>
                        <td>{r.output_text.slice(0, 74)}{r.output_text.length > 74 ? "…" : ""}</td>
                        <td className="k">
                          {r.band} · {r.score}
                        </td>
                        <td className="k">
                          {r.decision} · {r.risk}
                        </td>
                        <td className="k">
                          {r.false_certainty ? "false-certainty " : ""}
                          {r.degraded ? "degraded" : ""}
                          {!r.false_certainty && !r.degraded ? "—" : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="fig-cap">
                A customer&rsquo;s retention policy typically requires this for years — the
                fictional one in our corpus asks for seven, reproducible within five working
                days.
              </div>
            </div>
          </>
        ) : null}
      </section>
    </>
  );
}

// --- method ------------------------------------------------------------------

function MethodPage({ health }: { health: Health | null }) {
  return (
    <>
      <div className="titleblock">
        <h1>Why trust the verifier and not the model it is checking?</h1>
        <div className="meta">
          <span>
            Sheet <b>04</b>
          </span>
          <span>Method</span>
        </div>
      </div>

      <section className="section">
        <p className="lede col">
          It is the first question worth asking, and the honest answer is that most of the
          verdict does not come from a model at all.
        </p>

        <div className="fig">
          <div className="fig-head">
            <span>Table 01</span>
            <b>Three layers, in order of authority</b>
            <span className="right">every claim records which one ruled</span>
          </div>
          <div className="fig-body scroller">
            <table className="tbl" style={{ minWidth: "48rem" }}>
              <thead>
                <tr>
                  <th scope="col">Layer</th>
                  <th scope="col">What it is</th>
                  <th scope="col">Can a model override it?</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="k">deterministic</td>
                  <td>
                    Date arithmetic against a reference clock. Figure comparison with unit
                    normalisation. Whether a cited document exists at all.
                  </td>
                  <td>No. Hard verdict.</td>
                </tr>
                <tr>
                  <td className="k">grounded</td>
                  <td>
                    The deciding source passage is fetched and shown next to the claim, with its
                    document, section and page.
                  </td>
                  <td>No — you adjudicate by reading it.</td>
                </tr>
                <tr>
                  <td className="k">judge</td>
                  <td>
                    Entailment between evidence and claim, strict rubric, reasoning always
                    recorded.
                  </td>
                  <td>Only for fuzzy prose, and never alone for a BLOCK.</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="fig-cap">
            That last cell is enforced in code, not policy. Decision rule{" "}
            <span className="mono">R-JUDGE-ONLY</span> routes an output to human REVIEW when the
            only thing condemning it is the judge model&rsquo;s opinion, with no deterministic
            check agreeing. An LLM is never the sole authority for the strongest action the
            system can take.
          </div>
        </div>

        <div className="fig">
          <div className="fig-head">
            <span>Note 01</span>
            <b>Four things this deliberately will not do</b>
          </div>
          <div className="fig-body stack">
            <p className="small">
              <b>1 · It will not guess.</b> A claim with no retrievable evidence comes back{" "}
              <b>unknown</b>, shown amber, never red. Absence of evidence is not evidence of
              error, and a validator that fudges this is one the user learns to overrule.
            </p>
            <p className="small">
              <b>2 · It will not flag an opinion as wrong.</b> &ldquo;My name might be
              Mark&rdquo; is a hedged personal statement no corpus can falsify, so it is reported
              as <b>not checkable</b>. Crying wolf on someone&rsquo;s own name is how a
              validator loses its audience — and it is the specific failure that prompted this
              build.
            </p>
            <p className="small">
              <b>3 · It will not print a single score and stop.</b> The ledger is the result;
              the number is derived from it and shown second. &ldquo;87% reliable&rdquo; is
              meaningless and quietly trains everyone to ignore it.
            </p>
            <p className="small">
              <b>4 · It will not hide its own failures.</b> When the judge is unreachable, the
              affected claims say so and the run is marked degraded. An outage on our side must
              never look identical to a gap in the evidence.
            </p>
          </div>
        </div>

        <div className="fig">
          <div className="fig-head">
            <span>Note 02</span>
            <b>Configuration in this deployment</b>
          </div>
          <div className="fig-body scroller">
            <table className="tbl" style={{ minWidth: "40rem" }}>
              <tbody>
                <tr>
                  <td className="k">model</td>
                  <td>{health?.model.model_id ?? "not configured"}</td>
                </tr>
                <tr>
                  <td className="k">retrieval</td>
                  <td>{health?.corpus.retrieval ?? "—"}</td>
                </tr>
                <tr>
                  <td className="k">corpus</td>
                  <td>
                    {health?.corpus.documents ?? 0} documents, {health?.corpus.chunks ?? 0} chunks
                  </td>
                </tr>
                <tr>
                  <td className="k">decision table</td>
                  <td className="k">{health?.decision_table ?? "—"}</td>
                </tr>
                <tr>
                  <td className="k">signing key</td>
                  <td className="k">
                    {health?.signing.key_id ?? "—"}
                    {health?.signing.ephemeral ? " — ephemeral, not a configured identity" : ""}
                  </td>
                </tr>
                <tr>
                  <td className="k">audit log</td>
                  <td>{health?.audit_log.configured ? "configured" : "not configured"}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <p className="small col">
          This is a working slice of Project Sentinel&rsquo;s Level 4 — Verified. The module
          numbers throughout (MP-04, MP-09, MP-11, MP-12, MP-15…) are the same catalogue IDs
          used in the Sentinel brief, so the pipeline here maps directly onto the larger build
          rather than being a separate demo artefact.
        </p>
      </section>
    </>
  );
}
