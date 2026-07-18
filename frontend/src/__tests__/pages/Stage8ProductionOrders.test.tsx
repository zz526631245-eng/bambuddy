import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductionOrdersPage } from '../../pages/ProductionOrdersPage';
import { ProductionOrderDetailPage } from '../../pages/ProductionOrderDetailPage';

const api = vi.hoisted(() => ({
  listOrders: vi.fn(),
  createOrder: vi.fn(),
  getOrder: vi.fn(),
  changeStatus: vi.fn(),
  previewJobs: vi.fn(),
  confirmJobs: vi.fn(),
}));
const products = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock('../../api/production', () => ({ productionApi: api }));
vi.mock('../../api/products', () => ({ productsApi: products }));

function wrapper(initial = '/production-orders') {
  const client = new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/production-orders" element={<ProductionOrdersPage/>}/>
          <Route path="/production-orders/:id" element={<ProductionOrderDetailPage/>}/>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Stage 8 production orders', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listOrders.mockResolvedValue([]);
    products.list.mockResolvedValue([{id:1,sku:'DEMO-1',name:'演示产品',is_active:true}]);
  });

  it('creates an order from a product and quantity', async () => {
    api.createOrder.mockResolvedValue({id:9,order_number:'PO-8',product_id:1,quantity:3,priority:2,status:'planned'});
    api.getOrder.mockResolvedValue({id:9,order_number:'PO-8',product_id:1,quantity:3,priority:2,status:'planned',product_snapshot:{name:'演示产品'},requirements:[],operations:[]});
    wrapper();
    fireEvent.click(await screen.findByRole('button',{name:/新建生产订单/}));
    fireEvent.change(screen.getByPlaceholderText('订单编号（不能重复）'),{target:{value:'PO-8'}});
    fireEvent.change(screen.getByRole('combobox'),{target:{value:'1'}});
    fireEvent.change(screen.getByLabelText('生产套数'),{target:{value:'3'}});
    fireEvent.change(screen.getByLabelText('优先级'),{target:{value:'2'}});
    fireEvent.click(screen.getByRole('button',{name:'创建并计算需要数量'}));
    await waitFor(() => expect(api.createOrder.mock.calls[0][0]).toEqual(expect.objectContaining({order_number:'PO-8',product_id:1,quantity:3,priority:2})));
  });

  it('previews jobs before saving and never calls a print endpoint', async () => {
    api.getOrder.mockResolvedValue({
      id:9,order_number:'PO-8',product_id:1,quantity:3,priority:0,status:'planned',
      product_snapshot:{name:'演示产品'},operations:[],requirements:[{
        id:4,component_id:2,unit_quantity:2,status:'pending',component_snapshot:{name:'外壳'},
        recipe_snapshot:{name:'外壳打印方案'},ledger:{planned:6,reserved:0,good:0,scrap:0,remaining:6},plate_jobs:[],
      }],
    });
    api.previewJobs.mockResolvedValue({order_id:9,items:[{requirement_id:4,planned_quantity:6,component_name:'外壳',print_plan_name:'外壳打印方案'}]});
    api.confirmJobs.mockResolvedValue({order_id:9,items:[]});
    wrapper('/production-orders/9');
    fireEvent.click(await screen.findByRole('button',{name:'预览打印任务草稿'}));
    expect(await screen.findByText('安排 6 个')).toBeInTheDocument();
    expect(api.confirmJobs).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'确认保存草稿'}));
    await waitFor(() => expect(api.confirmJobs).toHaveBeenCalledTimes(1));
  });
});
