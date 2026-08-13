/** Build the mobile URL that locks one real printer for a consumable scan. */
export function buildPrinterConsumableQrPayload(baseUrl: string, targetKey: string): string {
  const serverUrl = baseUrl.replace(/\/+$/, '');
  const params = new URLSearchParams({
    printer: targetKey,
    // The mobile app uses this value to switch away from a stale saved server
    // before looking up the printer. Keep it explicit instead of inferring it
    // from the page URL so future reverse-proxy/base-path deployments remain
    // compatible too.
    server: serverUrl,
  });
  return `${serverUrl}/printer-consumables?${params.toString()}`;
}
