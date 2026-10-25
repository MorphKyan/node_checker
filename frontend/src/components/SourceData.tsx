import type { JsonValue } from "../types";

export function SourceData({ value }: { value: JsonValue }) {
  if (value === null || typeof value !== "object") {
    return <span className={`whitespace-pre-wrap break-words ${typeof value === "boolean" ? "font-mono text-blue-700" : "text-slate-700"}`}>{value === "" ? '""' : String(value)}</span>;
  }
  const entries = Object.entries(value);
  if (!entries.length) return <span className="font-mono text-slate-400">{Array.isArray(value) ? "[]" : "{}"}</span>;
  return (
    <dl className="min-w-0 divide-y divide-slate-100">
      {entries.map(([key, item]) => (
        <div key={key} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-3 py-2 first:pt-0 last:pb-0">
          {item !== null && typeof item === "object" ? (
            <>
              <dt className="col-span-2 mb-2 break-all font-semibold text-slate-600">{key}</dt>
              <dd className="col-span-2 min-w-0 border-l-2 border-slate-200 pl-3"><SourceData value={item} /></dd>
            </>
          ) : (
            <>
              <dt className="break-all text-slate-500">{key}</dt>
              <dd className="min-w-0"><SourceData value={item} /></dd>
            </>
          )}
        </div>
      ))}
    </dl>
  );
}
