import { loadDotEnv, loadEnv } from "./env.js";
import { createApp } from "./app.js";
import { log } from "./logger.js";

await loadDotEnv();
const env = loadEnv();
const app = createApp({ env });

const server = app.listen(env.PORT, "0.0.0.0", () => {
  log.info("server.listening", { port: env.PORT, realtimeModel: env.OPENAI_REALTIME_MODEL, textModel: env.OPENAI_TEXT_MODEL });
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    log.info("server.shutdown", { signal });
    server.close(() => process.exit(0));
  });
}
