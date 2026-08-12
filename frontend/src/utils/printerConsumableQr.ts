/** Build the mobile URL that locks one real printer for a consumable scan. */
export function buildPrinterConsumableQrPayload(baseUrl: string, targetKey: string): string {
  return `${baseUrl.replace(/\/+$/, '')}/printer-consumables?printer=${encodeURIComponent(targetKey)}`;
}
