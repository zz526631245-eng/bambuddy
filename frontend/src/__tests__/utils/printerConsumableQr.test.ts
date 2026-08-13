import { describe, expect, it } from 'vitest';
import { buildPrinterConsumableQrPayload } from '../../utils/printerConsumableQr';

describe('buildPrinterConsumableQrPayload', () => {
  it('opens the direct-consumable page with the selected real-printer key', () => {
    expect(buildPrinterConsumableQrPayload('https://192.168.31.83:8019', 'printer:17')).toBe(
      'https://192.168.31.83:8019/printer-consumables?printer=printer%3A17&server=https%3A%2F%2F192.168.31.83%3A8019',
    );
  });

  it('removes a trailing slash before adding the page path', () => {
    expect(buildPrinterConsumableQrPayload('https://farm.example/', 'printer:1')).toBe(
      'https://farm.example/printer-consumables?printer=printer%3A1&server=https%3A%2F%2Ffarm.example',
    );
  });
});
