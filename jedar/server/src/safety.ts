import { createHmac } from "node:crypto";

/**
 * Turn an anonymous, client-generated install ID into a privacy-preserving
 * OpenAI safety identifier. The raw install ID is never sent to OpenAI and never
 * logged; the HMAC cannot be reversed without the server salt.
 */
export function safetyIdentifier(installId: string | undefined, salt: string): string {
  const subject = installId && /^[A-Za-z0-9-]{8,64}$/.test(installId) ? installId : "anonymous";
  return "jedar_" + createHmac("sha256", salt).update(subject).digest("hex").slice(0, 32);
}
