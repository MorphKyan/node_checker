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

export function scoreBuckets(nodes: NodeResult[]) {
  const buckets = [
    { name: "0-49", value: 0 },
    { name: "50-69", value: 0 },
    { name: "70-84", value: 0 },
    { name: "85-100", value: 0 },
  ];
  for (const node of nodes) {
    if (node.total_score < 50) buckets[0].value += 1;
    else if (node.total_score < 70) buckets[1].value += 1;
    else if (node.total_score < 85) buckets[2].value += 1;
    else buckets[3].value += 1;
  }
  return buckets;
}
