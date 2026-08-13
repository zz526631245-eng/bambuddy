/**
 * Base URL embedded in labels that are scanned by a different device.
 *
 * A QR generated from a loopback page is only useful on the same computer,
 * so deployments can provide VITE_PUBLIC_BASE_URL for the LAN/HTTPS address.
 *
 * This is deliberately only a build-time fallback. The settings page's
 * ``external_url`` is the authoritative runtime value and is passed by QR
 * callers whenever it has been loaded from the server.
 */
export function mobileBaseUrl(externalUrl?: string | null): string {
  const configuredRuntimeUrl = externalUrl?.trim();
  const configured = import.meta.env.VITE_PUBLIC_BASE_URL?.trim();
  return (configuredRuntimeUrl || configured || window.location.origin).replace(/\/+$/, '');
}

export function isLoopbackPage(): boolean {
  return ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
}
