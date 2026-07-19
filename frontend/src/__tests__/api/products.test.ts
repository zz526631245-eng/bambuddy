import { afterEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../../api/client';
import { productsApi } from '../../api/products';

afterEach(() => {
  setAuthToken(null);
  vi.restoreAllMocks();
});

describe('products API authenticated resources', () => {
  it('loads product images with the bearer token instead of a bare img URL', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(new Blob(['image'], { type: 'image/png' }), {
        status: 200,
        headers: { 'Content-Type': 'image/png' },
      }),
    );
    setAuthToken('product-token');

    const blob = await productsApi.getImageBlob(4, 9);

    expect(blob.type).toBe('image/png');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/products/4/images/9/file',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer product-token' }),
      }),
    );
  });

  it('exports a product archive with the bearer token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(new Blob(['zip'], { type: 'application/zip' }), {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="PRODUCT-7.bambuddy-product.zip"' },
      }),
    );
    setAuthToken('product-token');

    const result = await productsApi.exportArchive(4);

    expect(result.filename).toBe('PRODUCT-7.bambuddy-product.zip');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/products/4/export',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer product-token' }),
      }),
    );
  });
});
