import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getServices, type Services } from "@/src/lib/db";
import { DEFAULT_PREFERENCES, type Preferences } from "@/src/lib/preferences";
import type { JournalRepository } from "@/src/lib/journal";
import { applyReminderPlan, configureNotifications } from "@/src/lib/notificationService";
import type { ReminderPlan } from "@/src/lib/notifications";

type AppValue = {
  ready: boolean;
  error: string | null;
  prefs: Preferences;
  updatePrefs: (patch: Partial<Omit<Preferences, "installId">>) => Promise<Preferences>;
  journal: JournalRepository | null;
  deleteAllJournalData: () => Promise<number>;
  resetApp: () => Promise<void>;
};

const AppContext = createContext<AppValue | null>(null);

const BOOT_PREFS: Preferences = { ...DEFAULT_PREFERENCES, installId: "" };

export function AppProvider({ children }: { children: ReactNode }) {
  const [services, setServices] = useState<Services | null>(null);
  const [prefs, setPrefs] = useState<Preferences>(BOOT_PREFS);
  const [error, setError] = useState<string | null>(null);
  const planRef = useRef<ReminderPlan | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getServices();
        const loaded = await s.preferences.load();
        if (cancelled) return;
        setServices(s);
        setPrefs(loaded);
        planRef.current = { enabled: loaded.reminderEnabled, hour: loaded.reminderHour, minute: loaded.reminderMinute };
        await configureNotifications();
        // Re-assert the schedule silently (e.g. after reinstall); never asks for permission.
        if (loaded.reminderEnabled) await applyReminderPlan(null, planRef.current).catch(() => undefined);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not open local storage");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const updatePrefs = useCallback(
    async (patch: Partial<Omit<Preferences, "installId">>) => {
      if (!services) throw new Error("Not ready");
      const next = await services.preferences.save(patch);
      setPrefs(next);
      const nextPlan: ReminderPlan = { enabled: next.reminderEnabled, hour: next.reminderHour, minute: next.reminderMinute };
      await applyReminderPlan(planRef.current, nextPlan).catch(() => undefined);
      planRef.current = nextPlan;
      return next;
    },
    [services],
  );

  const deleteAllJournalData = useCallback(async () => {
    if (!services) return 0;
    return services.journal.removeAll();
  }, [services]);

  const resetApp = useCallback(async () => {
    if (!services) return;
    await services.journal.removeAll();
    const next = await services.preferences.reset();
    await applyReminderPlan(planRef.current, { enabled: false, hour: next.reminderHour, minute: next.reminderMinute }).catch(() => undefined);
    planRef.current = null;
    setPrefs(next);
  }, [services]);

  const value = useMemo<AppValue>(
    () => ({ ready: !!services, error, prefs, updatePrefs, journal: services?.journal ?? null, deleteAllJournalData, resetApp }),
    [services, error, prefs, updatePrefs, deleteAllJournalData, resetApp],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
