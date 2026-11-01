import type { JobStatus, NodeResult } from "./types";

export function formatTime(timestamp?: number | null): string {
  if (!timestamp) return "-";
  return new Date(timestamp * 1000).toLocaleString();
}

export function duration(job: JobStatus): string {
  const start = job.started_at || job.created_at;
  const end = job.finished_at || Math.floor(Date.now() / 1000);
  const seconds = Math.max(0, end - start);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function statusTone(status: string): "slate" | "green" | "blue" | "red" | "amber" {
  if (status === "completed") return "green";
  if (status === "running") return "blue";
  if (status === "failed") return "red";
  if (status === "queued") return "amber";
  return "slate";
}

export function groupCount(values: string[]): Array<{ name: string; value: number }> {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value || "未知", (counts.get(value || "未知") || 0) + 1);
  return Array.from(counts.entries()).map(([name, value]) => ({ name, value }));
}

export function riskBuckets(nodes: NodeResult[]) {
  const buckets = [
    { name: "0-24", value: 0 },
    { name: "25-49", value: 0 },
    { name: "50-74", value: 0 },
    { name: "75-100", value: 0 },
    { name: "未知", value: 0 },
  ];
  for (const node of nodes) {
    const risk = node.probe.risk_score;
    if (risk === null) buckets[4].value += 1;
    else if (risk < 25) buckets[0].value += 1;
    else if (risk < 50) buckets[1].value += 1;
    else if (risk < 75) buckets[2].value += 1;
    else buckets[3].value += 1;
  }
  return buckets;
}
