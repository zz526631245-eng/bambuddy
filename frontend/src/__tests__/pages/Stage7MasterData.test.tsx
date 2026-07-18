import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductsPage } from '../../pages/ProductsPage';

const {list,create}=vi.hoisted(()=>({list:vi.fn(),create:vi.fn()}));
vi.mock('../../api/products', () => ({
  productsApi: { list, create },
}));

function renderPage(){
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
  return render(<QueryClientProvider client={client}><MemoryRouter><ProductsPage/></MemoryRouter></QueryClientProvider>);
}

describe('Stage 7 products page',()=>{
 beforeEach(()=>{list.mockReset();create.mockReset();list.mockResolvedValue([{id:1,sku:'SKU-7',name:'测试产品',description:'说明',is_active:true}]);create.mockResolvedValue({id:2,sku:'NEW-7',name:'新产品',is_active:true});});
 it('lists master data and opens a product detail link',async()=>{renderPage();expect(await screen.findByText('测试产品')).toBeInTheDocument();expect(screen.getByRole('link')).toHaveAttribute('href','/products/1');});
 it('creates a product through the CRUD form',async()=>{renderPage();fireEvent.click(await screen.findByRole('button',{name:/新建产品/}));fireEvent.change(screen.getByPlaceholderText('SKU（唯一）'),{target:{value:'NEW-7'}});fireEvent.change(screen.getByPlaceholderText('产品名称'),{target:{value:'新产品'}});fireEvent.click(screen.getByRole('button',{name:'保存'}));await waitFor(()=>expect(create.mock.calls[0][0]).toEqual({sku:'NEW-7',name:'新产品',description:''}));});
});
