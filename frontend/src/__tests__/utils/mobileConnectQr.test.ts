import { describe, expect, it } from 'vitest';
import { buildMobileConnectQrPayload, parseMobileConnectQrPayload } from '../../utils/mobileConnectQr';

describe('mobile connection QR payload', () => {
  it('builds a credential-free payload and normalizes trailing slashes', () => {
    expect(buildMobileConnectQrPayload('https://192.168.1.20:8019///'))
      .toBe('bambuddy-app://connect?server=https%3A%2F%2F192.168.1.20%3A8019');
  });

  it('parses payloads produced by the desktop settings page', () => {
    expect(parseMobileConnectQrPayload('bambuddy-app://connect?server=https%3A%2F%2F192.168.1.20%3A8019/'))
      .toBe('https://192.168.1.20:8019');
  });

  it('rejects non-http server values', () => {
    expect(parseMobileConnectQrPayload('bambuddy-app://connect?server=file%3A%2F%2F%2Ftmp')).toBeNull();
    expect(parseMobileConnectQrPayload('not-a-qr')).toBeNull();
  });
});
