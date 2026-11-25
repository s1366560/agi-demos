import type {} from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import type {
  CronJobCreate,
  CronJobUpdate,
  CronJobResponse,
  CronJobRunListResponse,
} from "../web/types/cron";
import type {
  CronCapabilities,
  CronJobListParams,
  CronJobRunListParams,
} from "../web/services/cronService";

type Job = CronJobResponse & { revision: number };
const jobs = new Map<string, Job>();
const attempts = new Map<string, string>();

function remember(job: Job) {
  jobs.set(job.id, job);
  return job;
}

function selected(id: string) {
  const job = jobs.get(id);
  if (!job) throw new Error("schedule_revision_unavailable");
  return job;
}

async function mutate<T>(
  command: string,
  input: Record<string, unknown>,
  readResult: (result: unknown) => T | Promise<T>,
) {
  // Keep the same key after a lost reply so retrying a successful command cannot replay its effect.
  const fingerprint = JSON.stringify([command, input]);
  const key = attempts.get(fingerprint) ?? crypto.randomUUID();
  attempts.set(fingerprint, key);
  const result = await window.memstack.invoke(command, {
    ...input,
    idempotency_key: key,
  });
  const value = await readResult(result);
  attempts.delete(fingerprint);
  return value;
}

async function get(_project: string, id: string) {
  return remember(
    (await window.memstack.invoke("list-schedules", {
      view: "job",
      job_id: id,
    })) as Job,
  );
}

type ScheduleFields = Omit<
  CronJobUpdate,
  "schedule" | "payload" | "delivery"
> & {
  schedule?: { kind: string; config: Record<string, unknown> } | null;
  payload?: { kind: string; config: Record<string, unknown> } | null;
  delivery?: { kind: string } | null;
};

export function scheduleFields(
  data: ScheduleFields,
  old?: Pick<Job, "name" | "enabled" | "timezone">,
) {
  const schedule = data.schedule;
  const config = schedule?.config;
  const runAt = config?.run_at;
  const trigger = !schedule
    ? undefined
    : schedule.kind === "every"
      ? { kind: "every", interval_seconds: config?.interval_seconds }
      : schedule.kind === "cron"
        ? {
            kind: "cron",
            expr: config?.expr,
            timezone:
              config?.timezone ?? data.timezone ?? old?.timezone ?? "UTC",
          }
        : {
            kind: "at",
            run_at:
              typeof runAt === "string" ? new Date(runAt).toISOString() : runAt,
          };
  const action = data.payload
    ? {
        kind: data.payload.kind,
        text: data.payload.config[
          data.payload.kind === "agent_turn" ? "message" : "content"
        ],
      }
    : undefined;
  return {
    name: data.name ?? old?.name,
    enabled: data.enabled ?? old?.enabled ?? true,
    ...(trigger && { trigger }),
    ...(action && { action }),
    ...(data.timezone && { timezone: data.timezone }),
    ...(data.conversation_id && { conversation_id: data.conversation_id }),
    ...(data.delivery && { delivery_kind: data.delivery.kind }),
    ...(data.description != null && { description: data.description }),
    ...Object.fromEntries(
      (
        [
          "conversation_mode",
          "stagger_seconds",
          "timeout_seconds",
          "max_retries",
          "delete_after_run",
        ] as const
      ).flatMap((key) => (data[key] == null ? [] : [[key, data[key]]])),
    ),
  };
}

async function save(
  project: string,
  data: CronJobCreate | CronJobUpdate,
  old?: Job,
) {
  return mutate(
    "save-schedule",
    {
      ...(old && { job_id: old.id, expected_revision: old.revision }),
      ...scheduleFields(data, old),
    },
    (result) => get(project, (result as { id: string }).id),
  );
}

export const cronAPI = {
  capabilities: () =>
    window.memstack.invoke("list-schedules", {
      view: "capabilities",
    }) as Promise<CronCapabilities>,
  async list(_project: string, params: CronJobListParams = {}) {
    const page = (await window.memstack.invoke("list-schedules", {
      view: "workbench",
      ...params,
    })) as { items: Job[]; total: number };
    return { ...page, items: page.items.map(remember) };
  },
  get,
  create: (project: string, data: CronJobCreate) => save(project, data),
  update: (project: string, id: string, data: CronJobUpdate) =>
    save(project, data, selected(id)),
  toggle: (project: string, id: string, enabled: boolean) =>
    save(project, { enabled }, selected(id)),
  async delete(_project: string, id: string) {
    await mutate(
      "delete-schedule",
      { job_id: id, expected_revision: selected(id).revision },
      () => undefined,
    );
    jobs.delete(id);
  },
  async run(_project: string, id: string) {
    await mutate(
      "run-schedule",
      { job_id: id, expected_revision: selected(id).revision },
      () => undefined,
    );
  },
  listRuns: (_project: string, id: string, params: CronJobRunListParams = {}) =>
    window.memstack.invoke("list-schedules", {
      view: "workbench",
      job_id: id,
      ...params,
    }) as Promise<CronJobRunListResponse>,
};
