import express, { type ErrorRequestHandler, type Express } from "express";
import helmet from "helmet";
import cors from "cors";
import rateLimit from "express-rate-limit";
import type { Env } from "./env.js";
import { ContentRepository } from "./content.js";
import { OfflineGateway, OpenAIClient, type OpenAIGateway } from "./openai.js";
import { reflectionsRouter } from "./routes/reflections.js";
import { realtimeRouter } from "./routes/realtime.js";
import { textRouter } from "./routes/text.js";
import { log } from "./logger.js";

export type AppDeps = {
  env: Env;
  content?: ContentRepository;
  gateway?: OpenAIGateway;
};

export function createApp({ env, content, gateway }: AppDeps): Express {
  const repo = content ?? ContentRepository.fromFile();
  const ai: OpenAIGateway =
    gateway ?? (env.OPENAI_API_KEY ? new OpenAIClient(env) : new OfflineGateway());
  if (!env.OPENAI_API_KEY) log.warn("openai.offline", { reason: "OPENAI_API_KEY not set; using offline gateway" });

  const app = express();
  app.disable("x-powered-by");
  app.set("trust proxy", 1);

  app.use(helmet());
  app.use(
    cors({
      // Native apps send no Origin header and are allowed; browsers must match CORS_ORIGIN.
      origin: (origin, cb) => cb(null, !origin || env.corsOrigins.includes(origin)),
      methods: ["GET", "POST"],
      allowedHeaders: [
        "Content-Type",
        "X-Jedar-Faith",
        "X-Jedar-Mode",
        "X-Jedar-Voice",
        "X-Jedar-Reflection",
        "X-Jedar-Install",
      ],
      maxAge: 600,
    }),
  );

  const skipInTest = () => env.NODE_ENV === "test";
  const readLimiter = rateLimit({ windowMs: 60_000, limit: 120, standardHeaders: "draft-8", legacyHeaders: false, skip: skipInTest });
  const aiLimiter = rateLimit({ windowMs: 60_000, limit: 20, standardHeaders: "draft-8", legacyHeaders: false, skip: skipInTest });

  app.use(express.json({ limit: "32kb" }));
  app.use(express.text({ type: "application/sdp", limit: "64kb" }));

  app.get("/health", (_req, res) => {
    res.json({ ok: true, voice: !!env.OPENAI_API_KEY });
  });

  app.use("/api/reflections", readLimiter, reflectionsRouter(repo));
  app.use("/api/realtime", aiLimiter, realtimeRouter(env, repo, ai));
  app.use("/api/text", aiLimiter, textRouter(env, repo, ai));

  app.use((_req, res) => {
    res.status(404).json({ error: "Not found" });
  });

  const errorHandler: ErrorRequestHandler = (err, _req, res, _next) => {
    const status = typeof err?.status === "number" && err.status >= 400 && err.status < 600 ? err.status : 500;
    if (status >= 500) log.error("unhandled", { message: err instanceof Error ? err.message : "unknown" });
    // Generic messages only: never leak stack traces or upstream details.
    res.status(status).json({ error: status === 413 ? "Request too large" : status < 500 ? "Bad request" : "Something went wrong" });
  };
  app.use(errorHandler);

  return app;
}
