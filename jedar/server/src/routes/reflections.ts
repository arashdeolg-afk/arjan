import { Router } from "express";
import { z } from "zod";
import { FAITHS } from "../domain.js";
import { ContentRepository, ID_PATTERN, isValidLocalDate, toPublic } from "../content.js";

const todayQuery = z.object({
  faith: z.enum(FAITHS),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(isValidLocalDate, "date must be a real YYYY-MM-DD date").optional(),
});

const idParam = z.object({ id: z.string().regex(ID_PATTERN) });

export function reflectionsRouter(content: ContentRepository): Router {
  const router = Router();

  router.get("/today", (req, res) => {
    const parsed = todayQuery.safeParse(req.query);
    if (!parsed.success) {
      res.status(400).json({ error: "Invalid faith or date" });
      return;
    }
    const date = parsed.data.date ?? new Date().toISOString().slice(0, 10);
    const item = content.today(parsed.data.faith, date);
    if (!item) {
      res.status(404).json({ error: "No reflection available for this faith yet" });
      return;
    }
    res.setHeader("Cache-Control", "private, max-age=300");
    res.json({ date, reflection: toPublic(item) });
  });

  router.get("/:id", (req, res) => {
    const parsed = idParam.safeParse(req.params);
    const item = parsed.success ? content.get(parsed.data.id) : undefined;
    if (!item) {
      res.status(404).json({ error: "Reflection not found" });
      return;
    }
    res.json({ reflection: toPublic(item) });
  });

  return router;
}
