import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductionOrdersPage } from '../../pages/ProductionOrdersPage';
import { ProductionOrderDetailPage } from '../../pages/ProductionOrderDetailPage';

const api = vi.hoisted(() => ({
  listOrders: vi.fn(), listProductSummaries: vi.fn(), createOrder: vi.fn(), getOrder: vi.fn(),
  changeStatus: vi.fn(), cancelOrder: vi.fn(), previewJobs: vi.fn(), confirmJobs: vi.fn(),
  advanceWorkflow: vi.fn(), retrySlice: vi.fn(), realSlice: vi.fn(), cancelPlateJob: vi.fn(), deletePlateJob: vi.fn(), downloadSliceArtifact: vi.fn(), deleteOrder: vi.fn(),
}));
const products = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock('../../api/production', () => ({ productionApi: api }));
vi.mock('../../api/products', () => ({ productsApi: products }));

function wrapper(initial = '/production-orders') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initial]}><Routes><Route path="/production-orders" element={<ProductionOrdersPage />} /><Route path="/production-orders/:id" element={<ProductionOrderDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>);
}

describe('Production orders and product summaries', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listOrders.mockResolvedValue([]);
    api.listProductSummaries.mockResolvedValue([]);
    products.list.mockResolvedValue([{ id: 1, sku: 'DEMO-1', name: '演示产品', is_active: true }]);
  });

  it('creates an order from a product and quantity', async () => {
    products.list.mockResolvedValue([{ id: 1, sku: 'DEMO-1', name: '婕旂ず浜у搧', is_active: true, product_files: [{ id: 7, product_id: 1, name: 'demo.3mf', version: 1, is_active: true, strategy: 'auto_pack', component_ids: [], units_per_plate: 1, compatible_printer_models: [], filament_requirements: [] }] }]);
    api.createOrder.mockResolvedValue({ id: 9, order_number: 'PO-8', product_id: 1, quantity: 3, priority: 2, status: 'planned' });
    wrapper();
    fireEvent.click(await screen.findByRole('button', { name: '新建生产订单' }));
    fireEvent.click(screen.getByRole('button', { name: '选择产品' }));
    fireEvent.click(await screen.findByRole('button', { name: /DEMO-1/ }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '7' } });
    fireEvent.change(screen.getByLabelText('需要生产数量（套）'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('优先级'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: '创建并计算需求数量' }));
    await waitFor(() => expect(api.createOrder).toHaveBeenCalledWith(expect.objectContaining({ product_id: 1, quantity: 3, priority: 2 }), expect.anything()));
    expect(api.createOrder.mock.calls[0][0]).not.toHaveProperty('order_number');
  });

  it('blocks order creation and prompts for a source file when the product has none', async () => {
    wrapper();
    fireEvent.click(await screen.findByRole('button', { name: /新建生产订单/ }));
    fireEvent.click(screen.getByRole('button', { name: /选择产品/ }));
    fireEvent.click(await screen.findByRole('button', { name: /DEMO-1/ }));
    expect(await screen.findByText('请先上传产品源文件')).toBeInTheDocument();
    const submitButton = screen.getAllByRole('button').find(button => button.getAttribute('type') === 'submit');
    expect(submitButton).toBeDefined();
    expect(submitButton).toBeDisabled();
    expect(api.createOrder).not.toHaveBeenCalled();
  });

  it('searches products in the picker and shows product identity', async () => {
    products.list.mockResolvedValue([
      { id: 1, sku: 'DEMO-1', name: '演示产品', is_active: true },
      { id: 2, sku: 'OTHER-2', name: '另一个产品', is_active: true },
    ]);
    wrapper();
    fireEvent.click(await screen.findByRole('button', { name: '新建生产订单' }));
    fireEvent.click(screen.getByRole('button', { name: '选择产品' }));
    fireEvent.change(screen.getByLabelText('搜索产品'), { target: { value: 'OTHER-2' } });
    expect(screen.getByRole('button', { name: /另一个产品.*OTHER-2/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /演示产品.*DEMO-1/ })).not.toBeInTheDocument();
  });

  it('shows product-level production totals and appends a new quantity record', async () => {
    api.listOrders.mockResolvedValue([{ id: 9, order_number: 'PO-8', product_id: 1, quantity: 3, priority: 0, status: 'planned' }]);
    api.listProductSummaries.mockResolvedValue([{ product_id: 1, total_quantity: 8, completed_quantity: 3, pending_quantity: 5 }]);
    products.list.mockResolvedValue([{ id: 1, sku: 'DEMO-1', name: '演示产品', is_active: true, images: [], product_files: [{ id: 7, product_id: 1, name: 'demo.3mf', version: 2, is_active: true, strategy: 'auto_pack', component_ids: [], units_per_plate: 1, compatible_printer_models: [], filament_requirements: [] }] }]);
    api.createOrder.mockResolvedValue({ id: 10, order_number: 'ADD-1', product_id: 1, quantity: 5, priority: 0, status: 'planned' });
    wrapper();
    expect(await screen.findByText('8')).toBeInTheDocument();
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('待生产')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '追加生产数量' }));
    fireEvent.change(screen.getByLabelText('追加生产数量'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: '确认追加' }));
    await waitFor(() => expect(api.createOrder).toHaveBeenCalledWith(expect.objectContaining({ product_id: 1, product_file_id: 7, quantity: 5 })));
  });

  it('confirms jobs for automatic simulated allocation and never calls a print endpoint', async () => {
    api.getOrder.mockResolvedValue({ id: 9, order_number: 'PO-8', product_id: 1, quantity: 3, priority: 0, status: 'planned', product_snapshot: { name: '演示产品' }, operations: [], requirements: [{ id: 4, component_id: 2, unit_quantity: 2, status: 'pending', component_snapshot: { name: '外壳' }, recipe_snapshot: { name: '外壳打印方案' }, ledger: { planned: 6, reserved: 0, good: 0, scrap: 0, remaining: 6 }, plate_jobs: [] }] });
    api.previewJobs.mockResolvedValue({ order_id: 9, items: [{ requirement_id: 4, planned_quantity: 6, component_name: '外壳', print_plan_name: '外壳打印方案' }] });
    api.confirmJobs.mockResolvedValue({ order_id: 9, items: [] });
    wrapper('/production-orders/9');
    fireEvent.click(await screen.findByRole('button', { name: '预览打印任务草稿' }));
    expect(await screen.findByText(/安排 6 套/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认并自动分配' }));
    await waitFor(() => expect(api.confirmJobs).toHaveBeenCalledTimes(1));
  });

  it('shows whether a production task was automatically assigned', async () => {
    api.getOrder.mockResolvedValue({ id: 9, order_number: 'PO-9', product_id: 1, quantity: 1, priority: 0, status: 'planned', product_snapshot: { name: '演示产品' }, operations: [], requirements: [{ id: 4, component_id: 2, unit_quantity: 1, status: 'in_progress', component_snapshot: { name: '外壳' }, recipe_snapshot: { name: '外壳打印方案' }, ledger: { planned: 1, reserved: 1, good: 0, scrap: 0, remaining: 0 }, plate_jobs: [{ id: 7, requirement_id: 4, printer_profile_id: 3, queue_item_id: 42, planned_quantity: 1, status: 'assigned' }] }] });
    wrapper('/production-orders/9');
    expect(await screen.findByText(/打印任务 #7/)).toBeInTheDocument();
  });

  it('lets an operator advance a virtual job and confirm partial quality', async () => {
    api.advanceWorkflow.mockResolvedValue({});
    api.getOrder.mockResolvedValue({ id: 11, order_number: 'PO-11', product_id: 1, quantity: 3, priority: 0, status: 'planned', product_snapshot: { name: '质检产品' }, operations: [], requirements: [{ id: 8, component_id: null, unit_quantity: 1, status: 'in_progress', component_snapshot: { name: '产品' }, recipe_snapshot: { name: '源文件' }, ledger: { planned: 3, reserved: 3, good: 0, scrap: 0, remaining: 0 }, plate_jobs: [{ id: 17, requirement_id: 8, printer_profile_id: 3, virtual_printer_id: 2, virtual_printer_name: '阶段11虚拟打印机', planned_quantity: 3, status: 'waiting_cleanup', workflow_status: 'awaiting_quality', slice_status: 'succeeded', slice_attempts: 1, created_at: '', updated_at: '' }] }] });
    wrapper('/production-orders/11');
    expect((await screen.findAllByText('待质检')).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText('任务 17 合格数量'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: '确认部分合格' }));
    await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledWith(17, 'quality', { good_quantity: 2 }));
  });
});
