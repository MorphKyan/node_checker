import { useQueries, useQuery } from "@tanstack/react-query";
import { ApiError, type ApiClient } from "./api";
import type { JobStatus, LocalPreferences } from "./types";

export function useAppData(api: ApiClient, preferences: LocalPreferences) {
  const subscriptions = useQuery({
    queryKey: ["subscriptions", preferences.apiBaseUrl],
    queryFn: api.listSubscriptions,
    refetchInterval: preferences.autoRefresh ? 15_000 : false,
  });

  const results = useQueries({
    queries: (subscriptions.data || []).map((subscription) => ({
      queryKey: ["results", preferences.apiBaseUrl, subscription.id, subscription.url],
      queryFn: async () => {
        try {
          return await api.getResults(subscription.id);
        } catch (error) {
          if (error instanceof ApiError && error.status === 409) return null;
          throw error;
        }
      },
      enabled: Boolean(subscription.id),
      refetchInterval: preferences.autoRefresh ? 15_000 : false,
    })),
  });

  const jobIds = Array.from(
    new Set((subscriptions.data || []).map((subscription) => subscription.last_job_id).filter(Boolean) as string[]),
  );
  const jobs = useQueries({
    queries: jobIds.map((jobId) => ({
      queryKey: ["job", preferences.apiBaseUrl, jobId],
      queryFn: () => api.getJob(jobId),
      refetchInterval: (query: { state: { data?: JobStatus } }) => {
        const status = query.state.data?.status;
        return preferences.autoRefresh && (status === "queued" || status === "running") ? 2_000 : 15_000;
      },
    })),
  });

  return { subscriptions, results, jobs };
}
