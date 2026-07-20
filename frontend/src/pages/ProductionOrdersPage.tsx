import { useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { Box, ClipboardList, Plus } from 'lucide-react';
import { productionApi } from '../api/production';
import { productsApi } from '../api/products';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';

const statusText: Record<string, string> = { draft: '草稿', planned: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消' };
const imageUrl = (productId: number, imageId: number) => `/api/v1/products/${productId}/images/${imageId}/file`;

export function ProductionOrdersPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: orders = [] } = useQuery({ queryKey: ['production-orders'], queryFn: productionApi.listOrders });
  const { data: summaries = [] } = useQuery({ queryKey: ['production-product-summaries'], queryFn: productionApi.listProductSummaries });
  const { data: products = [] } = useQuery({ queryKey: ['products'], queryFn: productsApi.list });
  const [show, setShow] = useState(false);
  const [productPickerOpen, setProductPickerOpen] = useState(false);
  const [productSearch, setProductSearch] = useState('');
  const [addingProductId, setAddingProductId] = useState<number | null>(null);
  const [additionalQuantity, setAdditionalQuantity] = useState(1);
  const [form, setForm] = useState({ product_id: 0, product_file_id: 0, quantity: 1, priority: 0, due_at: '', notes: '' });
  const create = useMutation({ mutationFn: productionApi.createOrder, onSuccess: order => { queryClient.invalidateQueries({ queryKey: ['production-orders'] }); queryClient.invalidateQueries({ queryKey: ['production-product-summaries'] }); setShow(false); navigate(`/production-orders/${order.id}`); } });
  const append = useMutation({
    mutationFn: ({ productId, quantity }: { productId: number; quantity: number }) => {
      const product = products.find(item => item.id === productId);
      const latestFile = product?.product_files?.filter(file => file.is_active && (product.production_mode !== 'multi_plate' || file.source_plate_index === 0)).sort((a, b) => b.version - a.version)[0];
      return productionApi.createOrder({ product_id: productId, product_file_id: latestFile?.id ?? null, quantity, priority: 0, due_at: null, notes: '追加生产数量' });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['production-orders'] }); queryClient.invalidateQueries({ queryKey: ['production-product-summaries'] }); setAddingProductId(null); setAdditionalQuantity(1); },
  });
  const selectedProduct = products.find(product => product.id === form.product_id);
  const hasActiveSourceFile = Boolean(selectedProduct?.product_files?.some(file => file.is_active && (selectedProduct.production_mode !== 'multi_plate' || file.source_plate_index === 0)));
  const filteredProducts = products.filter(product => `${product.sku} ${product.name}`.toLocaleLowerCase().includes(productSearch.trim().toLocaleLowerCase()));
  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate({ ...form, product_file_id: form.product_file_id || null, due_at: form.due_at ? new Date(form.due_at).toISOString() : null }); };
  const productIdsWithOrders = new Set(orders.map(order => order.product_id));
  const summaryByProduct = new Map(summaries.map(summary => [summary.product_id, summary]));
  const addQuantity = (event: FormEvent, productId: number) => { event.preventDefault(); if (additionalQuantity > 0 && !append.isPending) append.mutate({ productId, quantity: additionalQuantity }); };

  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <div className="flex flex-wrap justify-between gap-4"><div><h1 className="text-3xl font-bold text-white">生产订单</h1><p className="text-bambu-gray mt-1">选择产品和产品源文件，系统根据文件版本创建生产快照。</p></div><Button onClick={() => setShow(!show)}><Plus size={18} />新建生产订单</Button></div>
    {show && <Card><CardContent><form onSubmit={submit} className="grid md:grid-cols-3 gap-3">
      <p className="text-sm text-bambu-gray md:col-span-3">订单编号由系统自动生成，例如 PO-20260720-001。</p>
      <Button type="button" variant="secondary" className="justify-start" onClick={() => { setProductPickerOpen(true); setProductSearch(''); }}>{selectedProduct ? `${selectedProduct.sku} · ${selectedProduct.name}` : '选择产品'}</Button>
      {hasActiveSourceFile ? <select required value={form.product_file_id} onChange={event => setForm({ ...form, product_file_id: Number(event.target.value) })} className="stage8-input"><option value={0}>选择产品源文件</option>{selectedProduct?.product_files?.filter(file => file.is_active && (selectedProduct.production_mode !== 'multi_plate' || file.source_plate_index === 0)).map(file => <option key={file.id} value={file.id}>{file.product_color || '未命名颜色'} · {file.name} · v{file.version} · {selectedProduct?.production_mode === 'multi_plate' ? `多盘产品（${selectedProduct.source_plate_count} 盘/套）` : file.strategy === 'auto_pack' ? '自动摆盘' : '固定摆盘'}</option>)}</select> : selectedProduct ? <p role="alert" className="text-amber-300 md:col-span-2">请先上传产品源文件</p> : null}
      <label className="text-white">需要生产数量（套）<input aria-label="需要生产数量（套）" required type="number" min="1" value={form.quantity} onChange={event => setForm({ ...form, quantity: Number(event.target.value) })} className="stage8-input block w-full mt-1" placeholder="需要生产数量（套）" /></label>
      <label className="text-white">优先级<input aria-label="优先级" type="number" min="0" value={form.priority} onChange={event => setForm({ ...form, priority: Number(event.target.value) })} className="stage8-input block w-full mt-1" /></label>
      <label className="text-white">要求完成时间<input aria-label="要求完成时间" type="datetime-local" value={form.due_at} onChange={event => setForm({ ...form, due_at: event.target.value })} className="stage8-input block w-full mt-1" /></label>
      <input placeholder="订单备注（可不填）" value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} className="stage8-input" />
      <Button type="submit" disabled={!form.product_id || !hasActiveSourceFile || !form.product_file_id || create.isPending}>{create.isPending ? '创建中…' : '创建并计算需求数量'}</Button>
      {create.error && <p role="alert" className="text-red-400 md:col-span-3">{create.error instanceof Error ? create.error.message : '订单创建失败'}</p>}
    </form></CardContent></Card>}

    {productPickerOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="选择产品">
      <div className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-xl border border-bambu-gray-dark bg-bambu-dark shadow-2xl">
        <div className="flex items-center justify-between border-b border-bambu-gray-dark p-4"><h2 className="text-xl font-semibold text-white">选择产品</h2><Button type="button" variant="ghost" aria-label="关闭产品选择" onClick={() => setProductPickerOpen(false)}>×</Button></div>
        <div className="p-4"><input autoFocus aria-label="搜索产品" placeholder="搜索产品名称或编码" value={productSearch} onChange={event => setProductSearch(event.target.value)} className="stage8-input w-full" /></div>
        <div className="max-h-[55vh] overflow-y-auto px-4 pb-4 space-y-2">{filteredProducts.length === 0 ? <p className="py-8 text-center text-bambu-gray">没有匹配的产品</p> : filteredProducts.map(product => { const image = product.images?.[0]; return <button type="button" key={product.id} className="flex w-full items-center gap-3 rounded-lg border border-bambu-gray-dark bg-bambu-dark-secondary p-3 text-left hover:border-bambu-green" onClick={() => { setForm({ ...form, product_id: product.id, product_file_id: 0 }); setProductPickerOpen(false); }}>
          <div className="h-14 w-14 shrink-0 overflow-hidden rounded bg-bambu-dark-tertiary flex items-center justify-center">{image ? <img src={imageUrl(product.id, image.id)} alt="" className="h-full w-full object-cover" /> : <Box className="text-bambu-gray" size={24} />}</div><div className="min-w-0"><div className="truncate font-medium text-white">{product.name}</div><div className="text-sm text-bambu-green">{product.sku}</div></div>
        </button>; })}</div>
      </div>
    </div>}

    {productIdsWithOrders.size > 0 && <section className="space-y-3"><h2 className="text-xl font-semibold text-white">产品生产汇总</h2><div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{products.filter(product => productIdsWithOrders.has(product.id)).map(product => {
      const summary = summaryByProduct.get(product.id) ?? { total_quantity: 0, completed_quantity: 0, pending_quantity: 0 };
      const image = product.images?.[0];
      return <Card key={product.id} className="overflow-hidden"><div className="flex gap-4 p-4"><div className="w-20 h-20 shrink-0 rounded bg-bambu-dark flex items-center justify-center overflow-hidden">{image ? <img src={imageUrl(product.id, image.id)} alt={product.name} className="w-full h-full object-cover" /> : <Box className="text-bambu-gray" size={30} />}</div><div className="min-w-0"><div className="text-xs text-bambu-green">{product.sku}</div><h3 className="text-lg text-white font-semibold truncate">{product.name}</h3><Link className="text-sm text-bambu-green hover:underline" to={`/products/${product.id}`}>查看产品</Link></div></div><CardContent className="pt-0"><div className="grid grid-cols-3 gap-2 text-center"><div className="rounded bg-bambu-dark p-2"><div className="text-xs text-bambu-gray">总需求</div><div className="text-xl text-white">{summary.total_quantity}</div></div><div className="rounded bg-bambu-dark p-2"><div className="text-xs text-bambu-gray">已完成</div><div className="text-xl text-green-400">{summary.completed_quantity}</div></div><div className="rounded bg-bambu-dark p-2"><div className="text-xs text-bambu-gray">待生产</div><div className="text-xl text-amber-300">{summary.pending_quantity}</div></div></div>{addingProductId === product.id ? <form className="mt-3 flex gap-2" onSubmit={event => addQuantity(event, product.id)}><input aria-label="追加生产数量" type="number" min="1" value={additionalQuantity} onChange={event => setAdditionalQuantity(Number(event.target.value))} className="stage8-input flex-1" /><Button type="submit" disabled={append.isPending}>确认追加</Button><Button type="button" variant="secondary" onClick={() => setAddingProductId(null)}>取消</Button></form> : <Button className="mt-3 w-full" variant="secondary" onClick={() => setAddingProductId(product.id)}>追加生产数量</Button>}{append.error && addingProductId === product.id && <p role="alert" className="text-red-400 text-sm mt-2">{append.error instanceof Error ? append.error.message : '追加生产失败'}</p>}</CardContent></Card>;
    })}</div></section>}

    {orders.length === 0 ? <Card><CardContent className="text-center py-16 text-bambu-gray"><ClipboardList className="mx-auto mb-3" />还没有生产订单。</CardContent></Card> : <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{orders.map(order => <Link key={order.id} to={`/production-orders/${order.id}`}><Card className="h-full hover:border-bambu-green"><CardContent><div className="flex justify-between"><span className="font-mono text-bambu-green">{order.order_number}</span><span className="text-white">{statusText[order.status] || order.status}</span></div><h2 className="text-xl text-white font-semibold mt-4">{String(order.product_snapshot?.name || `产品 ${order.product_id}`)}</h2><p className="text-bambu-gray mt-2">生产 {order.quantity} 套 · {String(order.product_file_snapshot?.name || '产品源文件')}</p><p className="text-bambu-green mt-5">查看数量进度和任务草稿 →</p></CardContent></Card></Link>)}</div>}
    <style>{`.stage8-input{background:#18181b;border:1px solid #3f3f46;border-radius:.5rem;padding:.55rem .75rem;color:white;min-width:0}`}</style>
  </div>;
}
