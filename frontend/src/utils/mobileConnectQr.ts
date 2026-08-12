/**
 * Payload used by the desktop Settings page and the Android mobile app to
 * bootstrap a connection without exposing credentials in the QR code.
 */
export function buildMobileConnectQrPayload(serverUrl: string): string {
  const normalized = serverUrl.trim().replace(/\/+$/, '');
  return `bambuddy-app://connect?server=${encodeURIComponent(normalized)}`;
}

/** Extract a Bambuddy server URL from a mobile connection QR payload. */
export function parseMobileConnectQrPayload(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;

  try {
    const url = new URL(value);
    if (url.protocol === 'bambuddy-app:') {
      const server = url.searchParams.get('server');
      return server ? normalizeServer(server) : null;
    }
    const server = url.searchParams.get('server');
    if (server) return normalizeServer(server);
  } catch {
    // A URL with an invalid scheme is not a valid connection QR.
  }
  return null;
}

function normalizeServer(value: string): string | null {
  const server = value.trim().replace(/\/+$/, '');
  return /^https?:\/\/[^\s/]+(?::\d+)?(?:\/[^\s]*)?$/i.test(server) ? server : null;
}
