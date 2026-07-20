import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductsPage } from '../../pages/ProductsPage';

const { list, createWithImage } = vi.hoisted(() => ({ list: vi.fn(), createWithImage: vi.fn() }));
vi.mock('../../api/products', () => ({ productsApi: { list, createWithImage } }));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><ProductsPage /></MemoryRouter></QueryClientProvider>);
}

describe('Stage 7 products page', () => {
  beforeEach(() => {
    list.mockReset(); createWithImage.mockReset();
    list.mockResolvedValue([{ id: 1, sku: 'SKU-7', name: '测试产品', description: '说明', is_active: true, images: [] }]);
    createWithImage.mockResolvedValue({ id: 2, sku: 'PRD-0001', name: '新产品', is_active: true, images: [] });
  });
  it('lists master data and opens a product detail link', async () => {
    renderPage(); expect(await screen.findByText('测试产品')).toBeInTheDocument(); expect(screen.getByRole('link')).toHaveAttribute('href', '/products/1');
  });
  it('creates a product with an image and an automatically generated code', async () => {
    renderPage(); fireEvent.click(await screen.findByRole('button', { name: /新建产品/ }));
    fireEvent.change(screen.getByPlaceholderText('产品名称'), { target: { value: '新产品' } });
    const input = screen.getByLabelText(/选择产品图片/); const file = new File(['png'], 'product.png', { type: 'image/png' });
    fireEvent.change(input, { target: { files: [file] } }); await waitFor(() => expect(screen.getByText('product.png')).toBeInTheDocument()); fireEvent.click(screen.getByRole('button', { name: '创建产品' }));
    await waitFor(() => expect(createWithImage).toHaveBeenCalledWith('新产品', '', file));
  });
});
