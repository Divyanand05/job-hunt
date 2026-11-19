"use client";

import { useEffect, useState, useCallback } from "react";
import {
  CheckCircle, Clock, XCircle, SkipForward, Send,
  RefreshCw, Download, ChevronRight, AlertTriangle,
  Briefcase, MapPin, Star, ExternalLink,
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Types ───────────────────────────────────────────────────────────────────

type Status =
  | "discovered" | "shortlisted" | "prepared"
  | "pending_review" | "approved" | "submitted"
  | "failed" | "skipped" | "withdrawn";

interface Answer {
  question: string;
  answer: string | null;
  confidence: "HIGH" | "LOW" | "NEEDS_MANUAL_REVIEW";
  source: string;
  is_sensitive: boolean;
}

interface AuditEvent {
  timestamp: string;
  actor: string;
  event: string;
  old_value: string | null;
  new_value: string | null;
  detail: string | null;
}

interface Application {
  id: string;
  job_title: string;
  company: string;
  source: string;
  apply_url: string;
  score: number;
  resume_used: string;
  status: Status;
  cover_note: string | null;
  answers: Answer[];
  created_at: string;
  posted_at: string | null;
  job_location: string;
  job_salary: string | null;
  match_reasons: string[];
  missing_skills: string[];
  flags: string[];
  audit_log?: AuditEvent[];
}

interface Stats {
  counts: Record<string, number>;
  total: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<Status, string> = {
  discovered: "Discovered",
  shortlisted: "Shortlisted",
  prepared: "Prepared",
  pending_review: "Pending Review",
  approved: "Approved",
  submitted: "Submitted",
  failed: "Failed",
  skipped: "Skipped",
  withdrawn: "Withdrawn",
};

const STATUS_COLOR: Record<Status, string> = {
  discovered: "bg-gray-100 text-gray-700",
  shortlisted: "bg-yellow-100 text-yellow-800",
  prepared: "bg-blue-100 text-blue-800",
  pending_review: "bg-orange-100 text-orange-800",
  approved: "bg-green-100 text-green-700",
  submitted: "bg-purple-100 text-purple-800",
  failed: "bg-red-100 text-red-700",
  skipped: "bg-gray-100 text-gray-500",
  withdrawn: "bg-gray-100 text-gray-400",
};

const RESUME_LABEL: Record<string, string> = {
  aiml: "AI/ML Resume",
  data: "Data Resume",
  backend: "Backend Resume",
  main: "General Resume",
};

const CONF_COLOR: Record<string, string> = {
  HIGH: "text-green-600",
  LOW: "text-yellow-600",
  NEEDS_MANUAL_REVIEW: "text-red-600",
};

const ALL_STATUSES: Status[] = [
  "pending_review", "approved", "submitted",
  "shortlisted", "prepared", "skipped", "withdrawn", "failed",
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtDate(s: string | null) {
  if (!s) return "—";
  return new Date(s).toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function ScoreBar({ score }: { score: number }) {
  const color =
    score >= 80 ? "from-purple-500 to-indigo-500"
    : score >= 60 ? "from-yellow-400 to-orange-400"
    : "from-red-400 to-red-500";
  return (
    <div className="mt-1">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>Match Score</span>
        <span className="font-semibold text-gray-800">{score}/100</span>
      </div>
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${color} transition-all`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [apps, setApps] = useState<Application[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<Application | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>("pending_review");
  const [minScore, setMinScore] = useState(0);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    const r = await fetch(`${API}/api/stats`);
    if (r.ok) setStats(await r.json());
  }, []);

  const fetchApps = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({ min_score: String(minScore) });
    if (filterStatus !== "all") params.set("status", filterStatus);
    const r = await fetch(`${API}/api/applications?${params}`);
    if (r.ok) {
      const data: Application[] = await r.json();
      setApps(data);
      if (data.length > 0 && (!selected || !data.find(a => a.id === selected.id))) {
        loadDetail(data[0].id);
      }
    }
    setLoading(false);
  }, [filterStatus, minScore]);

  const loadDetail = async (id: string) => {
    const r = await fetch(`${API}/api/applications/${id}`);
    if (r.ok) setSelected(await r.json());
  };

  useEffect(() => { fetchStats(); fetchApps(); }, [fetchStats, fetchApps]);

  async function doAction(id: string, status: Status, detail?: string) {
    setActionMsg(null);
    const r = await fetch(`${API}/api/applications/${id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, actor: "user", detail }),
    });
    if (r.ok) {
      setActionMsg(`Marked as ${STATUS_LABEL[status]}`);
      await fetchApps();
      await fetchStats();
      loadDetail(id);
    }
  }

  async function doSubmit(id: string) {
    const ref = prompt("Enter confirmation reference (or leave blank for 'manual'):", "manual");
    if (ref === null) return; // user cancelled
    const r = await fetch(`${API}/api/applications/${id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_ref: ref || "manual" }),
    });
    if (r.ok) {
      setActionMsg("Marked as Submitted!");
      await fetchApps();
      await fetchStats();
      loadDetail(id);
    }
  }

  const exportCSV = () => window.open(`${API}/api/export/csv`);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-50">
      {/* ── Header ── */}
      <header className="bg-gradient-to-r from-indigo-600 to-purple-700 text-white px-6 py-4 shadow-lg">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">🤖 AI Auto-Apply Agent</h1>
            <p className="text-indigo-200 text-sm mt-0.5">Divyanand M · 2027 Graduate · B.Tech AI & Data Science</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => { fetchApps(); fetchStats(); }}
              className="flex items-center gap-1.5 bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg text-sm transition">
              <RefreshCw size={14} /> Refresh
            </button>
            <button onClick={exportCSV}
              className="flex items-center gap-1.5 bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg text-sm transition">
              <Download size={14} /> Export CSV
            </button>
          </div>
        </div>
      </header>

      {/* ── Stats Row ── */}
      <div className="max-w-7xl mx-auto px-6 py-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: "Pending Review", key: "pending_review", color: "border-orange-400" },
          { label: "Approved", key: "approved", color: "border-green-500" },
          { label: "Submitted", key: "submitted", color: "border-purple-500" },
          { label: "Shortlisted", key: "shortlisted", color: "border-yellow-400" },
          { label: "Total", key: "__total__", color: "border-indigo-400" },
        ].map(({ label, key, color }) => (
          <div key={key} className={`bg-white rounded-xl p-4 shadow-sm border-l-4 ${color}`}>
            <p className="text-2xl font-bold text-gray-800">
              {key === "__total__"
                ? (stats?.total ?? 0)
                : (stats?.counts[key] ?? 0)}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* ── Main Layout ── */}
      <div className="max-w-7xl mx-auto px-6 pb-10 flex gap-5 items-start">

        {/* ── Left: Queue ── */}
        <div className="w-80 shrink-0">
          <div className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-4 border-b border-gray-100">
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300">
                <option value="all">All statuses</option>
                {ALL_STATUSES.map(s => (
                  <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                ))}
              </select>
              <div className="mt-2 flex items-center gap-2">
                <label className="text-xs text-gray-500">Min score</label>
                <input type="range" min={0} max={100} step={5} value={minScore}
                  onChange={e => setMinScore(Number(e.target.value))}
                  className="flex-1 accent-indigo-600" />
                <span className="text-xs font-medium w-7">{minScore}</span>
              </div>
            </div>

            <div className="max-h-[65vh] overflow-y-auto divide-y divide-gray-50">
              {loading && (
                <p className="text-center text-sm text-gray-400 py-8">Loading…</p>
              )}
              {!loading && apps.length === 0 && (
                <p className="text-center text-sm text-gray-400 py-8">No applications match.</p>
              )}
              {apps.map(app => (
                <button key={app.id} onClick={() => loadDetail(app.id)}
                  className={`w-full text-left px-4 py-3 hover:bg-indigo-50 transition group
                    ${selected?.id === app.id ? "bg-indigo-50 border-l-2 border-indigo-500" : ""}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-gray-800 truncate">{app.job_title}</p>
                      <p className="text-xs text-gray-500 truncate">{app.company}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className="text-xs font-bold text-indigo-600">{app.score}</span>
                      {app.flags.includes("has_manual_review_items") && (
                        <AlertTriangle size={12} className="text-orange-400" />
                      )}
                    </div>
                  </div>
                  <span className={`mt-1.5 inline-block text-xs px-2 py-0.5 rounded-full font-medium
                    ${STATUS_COLOR[app.status as Status]}`}>
                    {STATUS_LABEL[app.status as Status]}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── Right: Detail ── */}
        <div className="flex-1 min-w-0">
          {actionMsg && (
            <div className="mb-3 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-2 text-sm flex justify-between">
              {actionMsg}
              <button onClick={() => setActionMsg(null)} className="text-green-400 hover:text-green-600">✕</button>
            </div>
          )}

          {!selected ? (
            <div className="bg-white rounded-xl shadow-sm p-10 text-center text-gray-400">
              <Briefcase size={40} className="mx-auto mb-3 opacity-30" />
              <p>Select a job from the queue to review</p>
            </div>
          ) : (
            <div className="bg-white rounded-xl shadow-sm overflow-hidden">
              {/* Title block */}
              <div className="bg-gradient-to-r from-indigo-50 to-purple-50 px-6 py-5 border-b border-gray-100">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-xl font-bold text-gray-900">{selected.job_title}</h2>
                    <div className="flex flex-wrap items-center gap-3 mt-2 text-sm text-gray-600">
                      <span className="flex items-center gap-1"><Briefcase size={13} />{selected.company}</span>
                      <span className="flex items-center gap-1"><MapPin size={13} />{selected.job_location || "Remote"}</span>
                      <span className="text-gray-400">via {selected.source}</span>
                      {selected.job_salary && <span className="text-green-700 font-medium">💰 {selected.job_salary}</span>}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLOR[selected.status as Status]}`}>
                        {STATUS_LABEL[selected.status as Status]}
                      </span>
                      <span className="text-xs text-gray-400">{fmtDate(selected.posted_at)}</span>
                    </div>
                  </div>
                  <a href={selected.apply_url} target="_blank" rel="noreferrer"
                    className="shrink-0 flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
                    Apply Now <ExternalLink size={13} />
                  </a>
                </div>
                <div className="mt-4 max-w-sm">
                  <ScoreBar score={selected.score} />
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  Resume: <span className="font-medium text-gray-600">{RESUME_LABEL[selected.resume_used] || selected.resume_used}</span>
                </p>
              </div>

              <div className="p-6 space-y-5">
                {/* Match reasons */}
                {selected.match_reasons.length > 0 && (
                  <section>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Why You Qualify</h3>
                    <ul className="space-y-1">
                      {selected.match_reasons.map((r, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                          <CheckCircle size={14} className="text-green-500 mt-0.5 shrink-0" />{r}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {/* Missing skills */}
                {selected.missing_skills.length > 0 && (
                  <section>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Skills to Develop</h3>
                    <div className="flex flex-wrap gap-2">
                      {selected.missing_skills.map((s, i) => (
                        <span key={i} className="text-xs bg-orange-50 text-orange-700 border border-orange-200 px-2 py-0.5 rounded-full">{s}</span>
                      ))}
                    </div>
                  </section>
                )}

                {/* Cover note */}
                {selected.cover_note && (
                  <section>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Cover Note</h3>
                    <div className="bg-purple-50 border-l-4 border-purple-400 rounded-r-lg px-4 py-3 text-sm text-gray-700 leading-relaxed">
                      {selected.cover_note}
                    </div>
                  </section>
                )}

                {/* Screening answers */}
                {selected.answers.length > 0 && (
                  <section>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Screening Answers</h3>
                    <div className="space-y-3">
                      {selected.answers.map((a, i) => (
                        <div key={i} className="bg-gray-50 rounded-lg px-4 py-3">
                          <div className="flex items-center gap-2 mb-1">
                            <span className={`text-xs font-semibold ${CONF_COLOR[a.confidence]}`}>
                              {a.confidence === "HIGH" ? "✓" : a.confidence === "LOW" ? "~" : "⚠"} {a.confidence}
                            </span>
                            {a.is_sensitive && (
                              <span className="text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded">🔒 Sensitive</span>
                            )}
                          </div>
                          <p className="text-sm font-medium text-gray-700">{a.question}</p>
                          <p className="text-sm text-gray-500 mt-0.5">
                            {a.answer ?? <span className="italic text-orange-500">Needs manual input</span>}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Action buttons */}
                {["pending_review", "shortlisted", "prepared"].includes(selected.status) && (
                  <section className="flex gap-3 pt-2">
                    <button onClick={() => doAction(selected.id, "approved")}
                      className="flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition">
                      <CheckCircle size={15} /> Approve
                    </button>
                    <button onClick={() => doAction(selected.id, "skipped")}
                      className="flex items-center gap-2 bg-gray-200 hover:bg-gray-300 text-gray-700 px-5 py-2 rounded-lg text-sm font-medium transition">
                      <SkipForward size={15} /> Skip
                    </button>
                    <button onClick={() => doAction(selected.id, "withdrawn")}
                      className="flex items-center gap-2 bg-red-50 hover:bg-red-100 text-red-600 px-5 py-2 rounded-lg text-sm font-medium transition">
                      <XCircle size={15} /> Withdraw
                    </button>
                  </section>
                )}

                {selected.status === "approved" && (
                  <section className="bg-green-50 border border-green-200 rounded-lg p-4">
                    <p className="text-sm text-green-700 font-medium mb-3">
                      ✅ Approved — click Apply Now above to submit manually, then confirm below.
                    </p>
                    <button onClick={() => doSubmit(selected.id)}
                      className="flex items-center gap-2 bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition">
                      <Send size={14} /> Mark as Submitted
                    </button>
                  </section>
                )}

                {selected.status === "submitted" && (
                  <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 text-sm text-purple-700">
                    🚀 Submitted on {fmtDate((selected as any).submitted_at)}
                  </div>
                )}

                {/* Audit log */}
                {selected.audit_log && selected.audit_log.length > 0 && (
                  <section>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Audit Log</h3>
                    <div className="space-y-1 max-h-48 overflow-y-auto">
                      {selected.audit_log.map((e, i) => (
                        <div key={i} className="text-xs text-gray-500 flex gap-2">
                          <span className="text-gray-300 shrink-0">{fmtDate(e.timestamp)}</span>
                          <span className="text-indigo-400 shrink-0">{e.actor}</span>
                          <span>{e.event}{e.old_value ? ` : ${e.old_value} → ${e.new_value}` : ""}</span>
                          {e.detail && <span className="text-gray-400 italic">{e.detail}</span>}
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
