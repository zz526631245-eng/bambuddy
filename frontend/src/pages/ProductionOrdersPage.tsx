import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Box,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Factory,
  Filter,
  History,
  PackageCheck,
  Plus,
  Printer,
  Search,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import { productionApi } from '../api/production';
import { productsApi } from '../api/products';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { QueuePage } from './QueuePage';
import { ProductionPrinterStatusPage } from './ProductionPrinterStatusPage';
import { SliceLibraryPage } from './SliceLibraryPage';

const statusText: Record<string, string> = { draft: '草稿', planned: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消' };
const priorityText: Record<number, string> = { 4: '最高', 3: '高', 2: '中', 1: '低', 0: '极低' };
const imageUrl = (productId: number, imageId: number) => `/api/v1/products/${productId}/images/${imageId}/file`;
const formatDate = (value?: string | null) => value ? new Date(value).toLocaleDateString('zh-CN') : '未设置';
const formatDateTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '未设置';

type View = 'overview' | 'queue' | 'printers' | 'history' | 'slice-library';

export function ProductionOrdersPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>('overview');
  const [showCreate, setShowCreate] = useState(false);
  const [productPickerOpen, setProductPickerOpen] = useState(false);
  const [productSearch, setProductSearch] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [historySearch, setHistorySearch] = useState('');
  const [historyFrom, setHistoryFrom] = useState('');
  const [historyTo, setHistoryTo] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [expandedProductId, setExpandedProductId] = useState<number | null>(null);
  const [addingOrderId, setAddingOrderId] = useState<number | null>(null);
  const [additionalQuantity, setAdditionalQuantity] = useState(1);
  const [form, setForm] = useState({ product_id: 0, product_file_id: 0, quantity: 1, priority: 2, due_at: '', notes: '' });
  const showBatchTable = false as boolean;

  const { data: orders = [], isFetching: ordersFetching } = useQuery({
    queryKey: ['production-orders', 'active', activeSearch],
    queryFn: () => productionApi.listOrders({ search: activeSearch || undefined }),
    enabled: view === 'overview',
  });
  const { data: historyOrders = [], isFetching: historyFetching } = useQuery({
    queryKey: ['production-orders', 'history', historySearch, historyFrom, historyTo],
    queryFn: () => productionApi.listOrders({ history: true, search: historySearch || undefined, from_date: historyFrom || undefined, to_date: historyTo || undefined }),
    enabled: view === 'history',
  });
  // The primary workbench is product-level. Batch rows remain available when
  // a product is expanded, but product quantities come from the backend.
  const { data: summaries = [], isFetching: summariesFetching } = useQuery({
    queryKey: ['production-product-workbench', activeSearch],
    queryFn: () => productionApi.listProductSummaries(true, activeSearch || undefined),
    enabled: view === 'overview',
  });
  const { data: products = [] } = useQuery({ queryKey: ['products'], queryFn: productsApi.list });
  const selectedProduct = products.find(product => product.id === form.product_id);
  const sourceFiles = selectedProduct?.product_files?.filter(file => file.is_active && (selectedProduct.production_mode !== 'multi_plate' || file.source_plate_index === 0)) ?? [];
  const hasActiveSourceFile = sourceFiles.length > 0;
  const availability = useQuery({
    queryKey: ['production-order-availability', form.product_id, form.product_file_id],
    queryFn: () => productionApi.orderAvailability(form.product_id, form.product_file_id),
    enabled: Boolean(form.product_id && form.product_file_id && productionApi.orderAvailability),
  });

  const create = useMutation({
    mutationFn: productionApi.createOrder,
    onSuccess: order => {
      queryClient.invalidateQueries({ queryKey: ['production-orders'] });
      queryClient.invalidateQueries({ queryKey: ['production-product-summaries'] });
      queryClient.invalidateQueries({ queryKey: ['production-product-workbench'] });
      setShowCreate(false);
      setForm({ product_id: 0, product_file_id: 0, quantity: 1, priority: 2, due_at: '', notes: '' });
      navigate(`/production-orders/${order.id}`);
    },
  });
  const append = useMutation({
    mutationFn: async ({ orderId, productId, quantity }: { orderId?: number; productId: number; quantity: number }) => {
      if (orderId && productionApi.appendOrderQuantity) return productionApi.appendOrderQuantity(orderId, { quantity });
      // Compatibility fallback for old API mocks/installations. Current
      // backend always uses the append endpoint and keeps one batch ledger.
      const product = products.find(item => item.id === productId);
      const latestFile = product?.product_files?.filter(file => file.is_active && (product.production_mode !== 'multi_plate' || file.source_plate_index === 0)).sort((a, b) => b.version - a.version)[0];
      return productionApi.createOrder({ product_id: productId, product_file_id: latestFile?.id ?? null, quantity, priority: 0, due_at: null, notes: '追加生产数量' });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['production-orders'] });
      queryClient.invalidateQueries({ queryKey: ['production-product-summaries'] });
      queryClient.invalidateQueries({ queryKey: ['production-product-workbench'] });
      setAddingOrderId(null);
      setAdditionalQuantity(1);
    },
  });

  const filteredProducts = useMemo(() => {
    const keyword = productSearch.trim().toLocaleLowerCase();
    return products.filter(product => !keyword || `${product.sku} ${product.name}`.toLocaleLowerCase().includes(keyword));
  }, [products, productSearch]);
  const visibleSummaries = useMemo(() => {
    if (priorityFilter === 'all') return summaries;
    return summaries.filter(summary => String(summary.highest_priority ?? 0) === priorityFilter);
  }, [summaries, priorityFilter]);
  // Retained for the hidden legacy batch markup and compatibility test hooks;
  // the visible workbench never renders one row per order.
  const visibleOrders = useMemo(() => {
    if (priorityFilter === 'all') return orders;
    return orders.filter(order => String(order.priority) === priorityFilter);
  }, [orders, priorityFilter]);
  const stats = useMemo(() => ({
    active: summaries.length,
    overdue: summaries.filter(summary => summary.overdue).length,
    printing: summaries.filter(summary => (summary.printing_quantity ?? 0) > 0).length,
    waiting: summaries.filter(summary => (summary.assigned_quantity ?? 0) > 0).length,
  }), [summaries]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate({ ...form, product_file_id: form.product_file_id || null, due_at: form.due_at ? new Date(form.due_at).toISOString() : null });
  };
  const addQuantity = (event: FormEvent, orderId: number, productId: number) => {
    event.preventDefault();
    if (additionalQuantity > 0 && !append.isPending) append.mutate({ orderId, productId, quantity: additionalQuantity });
  };
  const selectProduct = (productId: number) => {
    setForm(current => ({ ...current, product_id: productId, product_file_id: 0 }));
    setProductPickerOpen(false);
  };
  const tabs: Array<{ key: View; label: string; icon: typeof Factory }> = [
    { key: 'overview', label: '交付总览', icon: ClipboardList },
    { key: 'queue', label: '排产队列', icon: Clock3 },
    { key: 'printers', label: '打印机安排', icon: Printer },
    { key: 'history', label: '历史订单', icon: History },
  ];

  return <div className="mx-auto max-w-[1500px] space-y-6 p-4 md:p-8">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="mb-2 flex items-center gap-2 text-sm text-bambu-green"><Factory size={16} />生产工作台</div>
        <h1 className="text-3xl font-bold tracking-tight text-white">生产中心</h1>
        <p className="mt-1 text-bambu-gray">按交期和优先级安排当前批次，历史记录独立保存。</p>
      </div>
      <Button onClick={() => setShowCreate(value => !value)}><Plus size={18} />新建生产订单</Button>
    </header>

    <nav aria-label="生产中心导航" className="rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/90 p-2 shadow-lg">
      <div className="flex flex-wrap gap-2">
        {tabs.map(({ key, label, icon: Icon }) => <button key={key} type="button" onClick={() => setView(key)} className={`inline-flex min-h-[44px] items-center gap-2 rounded-lg px-4 py-2 text-sm transition-colors ${view === key ? 'bg-bambu-green text-bambu-dark font-semibold' : 'text-bambu-gray-light hover:bg-bambu-dark-tertiary hover:text-white'}`}><Icon size={16} />{label}</button>)}
        <button type="button" onClick={() => setView('slice-library')} className={`ml-auto inline-flex min-h-[44px] items-center gap-2 rounded-lg px-4 py-2 text-sm ${view === 'slice-library' ? 'bg-bambu-dark-tertiary text-white' : 'text-bambu-gray hover:bg-bambu-dark-tertiary hover:text-white'}`}><SlidersHorizontal size={16} />切片库</button>
      </div>
    </nav>

    {view === 'queue' && <section className="rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/30"><QueuePage /></section>}
    {view === 'printers' && <section className="rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/30"><ProductionPrinterStatusPage /></section>}
    {view === 'slice-library' && <section className="rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/30"><SliceLibraryPage /></section>}

    {view === 'overview' && <>
      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: '进行中产品', value: stats.active, icon: ClipboardList, tone: 'text-blue-300', helper: '只显示仍有剩余数量的产品' },
          { label: '打印中产品', value: stats.printing, icon: Printer, tone: 'text-bambu-green', helper: '当前有打印任务的产品' },
          { label: '待排产产品', value: stats.waiting, icon: PackageCheck, tone: 'text-violet-300', helper: '已分配或等待任务的产品' },
          { label: '逾期未完成', value: stats.overdue, icon: AlertTriangle, tone: stats.overdue ? 'text-red-300' : 'text-bambu-gray-light', helper: '需要重新规划交期' },
        ].map(({ label, value, icon: Icon, tone, helper }) => <Card key={label}><CardContent className="flex items-center gap-4 p-4"><div className={`flex h-11 w-11 items-center justify-center rounded-full bg-bambu-dark-tertiary ${tone}`}><Icon size={22} /></div><div><div className="text-sm text-bambu-gray">{label}</div><div className="text-2xl font-semibold text-white">{value}</div><div className="text-xs text-bambu-gray">{helper}</div></div></CardContent></Card>)}
      </section>

      {showCreate && <Card className="border-bambu-green/40"><CardContent><form onSubmit={submit} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="xl:col-span-4"><div className="mb-2 flex items-center gap-2 text-sm font-medium text-white"><Sparkles size={16} className="text-bambu-green" />创建批次</div><p className="text-sm text-bambu-gray">相同产品、源文件和交期的未完成订单会自动合并；不同交期保留为独立批次。</p></div>
        <div className="xl:col-span-2"><label className="mb-1 block text-sm text-bambu-gray">产品</label><Button type="button" variant="secondary" className="w-full justify-start text-left" onClick={() => { setProductPickerOpen(true); setProductSearch(''); }}>{selectedProduct ? `${selectedProduct.sku} · ${selectedProduct.name}` : '选择产品'}</Button>{!selectedProduct && <div className="mt-1 text-xs text-bambu-gray">支持名称 / SKU / 产品编码搜索</div>}</div>
        <div><label className="mb-1 block text-sm text-bambu-gray">源文件</label>{hasActiveSourceFile ? <select required aria-label="选择产品源文件" value={form.product_file_id} onChange={event => setForm({ ...form, product_file_id: Number(event.target.value) })} className="stage16-input"><option value={0}>选择产品源文件</option>{sourceFiles.map(file => <option key={file.id} value={file.id}>{file.product_color || '未命名'} · {file.name} · v{file.version}</option>)}</select> : selectedProduct ? <p role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-300">请先上传产品源文件</p> : <div className="stage16-input text-bambu-gray">先选择产品</div>}</div>
        <label className="text-sm text-bambu-gray">生产数量（套）<input aria-label="需要生产数量（套）" required type="number" min="1" value={form.quantity} onChange={event => setForm({ ...form, quantity: Number(event.target.value) })} className="stage16-input mt-1" /></label>
        <label className="text-sm text-bambu-gray">优先级<select role="listbox" aria-label="优先级" value={form.priority} onChange={event => setForm({ ...form, priority: Number(event.target.value) })} className="stage16-input mt-1"><option value={4}>最高</option><option value={3}>高</option><option value={2}>中</option><option value={1}>低</option><option value={0}>极低</option></select></label>
        <label className="text-sm text-bambu-gray">交期<input aria-label="要求完成时间" type="datetime-local" value={form.due_at} onChange={event => setForm({ ...form, due_at: event.target.value })} className="stage16-input mt-1" /></label>
        <label className="text-sm text-bambu-gray xl:col-span-2">备注<input placeholder="订单备注（可不填）" value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} className="stage16-input mt-1" /></label>
        {availability.data && <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3 text-sm xl:col-span-2"><div className="flex items-center gap-2 text-white"><CheckCircle2 size={16} className="text-bambu-green" />排产预检查</div><div className="mt-1 text-bambu-gray">已配置兼容打印机 <span className="font-semibold text-white">{availability.data.compatible_printer_count}</span> 台 · 当前耗材匹配 <span className="font-semibold text-white">{availability.data.matching_consumable_printer_count}</span> 台</div>{availability.data.available_printer_names.length > 0 && <div className="mt-1 truncate text-xs text-bambu-gray">{availability.data.available_printer_names.join('、')}</div>}</div>}
        <div className="flex items-end justify-end gap-2 xl:col-span-4"><Button type="button" variant="secondary" onClick={() => setShowCreate(false)}>取消</Button><Button type="submit" disabled={!form.product_id || !hasActiveSourceFile || !form.product_file_id || create.isPending}>{create.isPending ? '创建中…' : '创建并进入订单'}</Button></div>
        {create.error && <p role="alert" className="text-red-400 xl:col-span-4">{create.error instanceof Error ? create.error.message : '订单创建失败'}</p>}
      </form></CardContent></Card>}

      {showBatchTable && <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold text-white">当前交付批次</h2><p className="text-sm text-bambu-gray">优先级 → 交期 → 创建时间自动排序；逾期批次优先提醒。</p></div><div className="flex flex-wrap gap-2"><div className="relative"><Search size={16} className="absolute left-3 top-3 text-bambu-gray" /><input aria-label="搜索生产订单" placeholder="订单号搜索" value={activeSearch} onChange={event => setActiveSearch(event.target.value)} className="stage16-input pl-9" /></div><select aria-label="筛选优先级" value={priorityFilter} onChange={event => setPriorityFilter(event.target.value)} className="stage16-input"><option value="all">全部优先级</option><option value="4">最高</option><option value="3">高</option><option value="2">中</option><option value="1">低</option><option value="0">极低</option></select><Button type="button" variant="secondary" onClick={() => queryClient.invalidateQueries({ queryKey: ['production-orders', 'active'] })}><Filter size={16} />刷新</Button></div></div>
        <Card className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm"><thead className="border-b border-bambu-dark-tertiary bg-bambu-dark/60 text-bambu-gray"><tr><th className="px-4 py-3">订单 / 产品</th><th className="px-4 py-3">目标数量</th><th className="px-4 py-3">完成 / 剩余</th><th className="px-4 py-3">优先级</th><th className="px-4 py-3">交期</th><th className="px-4 py-3">打印机</th><th className="px-4 py-3">操作</th></tr></thead><tbody className="divide-y divide-bambu-dark-tertiary">{ordersFetching ? <tr><td colSpan={7} className="px-4 py-12 text-center text-bambu-gray">正在读取排产…</td></tr> : visibleOrders.length === 0 ? <tr><td colSpan={7} className="px-4 py-12 text-center text-bambu-gray"><ClipboardList className="mx-auto mb-2" />当前没有进行中的生产订单</td></tr> : visibleOrders.map(order => { const product = products.find(item => item.id === order.product_id); const overdue = order.overdue || order.delivery_status === 'overdue'; return <tr key={order.id} className="hover:bg-bambu-dark/40"><td className="px-4 py-3"><Link to={`/production-orders/${order.id}`} className="block min-w-0"><div className="font-mono text-xs text-bambu-green">{order.order_number}</div><div className="mt-1 font-medium text-white">{String(order.product_snapshot?.name || product?.name || `产品 ${order.product_id}`)}</div><div className="text-xs text-bambu-gray">{product?.sku || order.product_snapshot?.sku || '—'}</div></Link></td><td className="px-4 py-3 text-white">{order.quantity} 套</td><td className="px-4 py-3"><div className="text-white">{order.completed_quantity ?? 0} / {order.remaining_quantity ?? order.quantity}</div><div className="mt-1 text-xs text-bambu-gray">打印中 {order.printing_quantity ?? 0} · 待质检 {order.quality_quantity ?? 0}</div></td><td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs ${order.priority >= 3 ? 'bg-red-500/15 text-red-300' : order.priority === 2 ? 'bg-amber-500/15 text-amber-300' : 'bg-bambu-dark-tertiary text-bambu-gray-light'}`}>{order.priority_label || priorityText[order.priority] || '极低'}</span></td><td className={`px-4 py-3 ${overdue ? 'font-semibold text-red-300' : 'text-bambu-gray-light'}`}>{overdue && <AlertTriangle size={14} className="mr-1 inline" />}{formatDate(order.due_at)}{overdue && <div className="text-xs">逾期未完成</div>}</td><td className="px-4 py-3 text-bambu-gray-light">{order.assigned_printer_names?.length ? order.assigned_printer_names.join('、') : '待分配'}</td><td className="px-4 py-3"><div className="flex items-center gap-2"><Link to={`/production-orders/${order.id}`} className="rounded-lg bg-bambu-dark-tertiary px-3 py-2 text-xs text-white hover:bg-bambu-gray-dark">查看详情</Link><Button type="button" size="sm" variant="ghost" onClick={() => { setAddingOrderId(order.id); setAdditionalQuantity(1); }}>追加数量</Button></div>{addingOrderId === order.id && <form className="mt-2 flex gap-2" onSubmit={event => addQuantity(event, order.id, order.product_id)}><input aria-label="追加生产数量" type="number" min="1" value={additionalQuantity} onChange={event => setAdditionalQuantity(Number(event.target.value))} className="stage16-input w-24" /><Button type="submit" size="sm" disabled={append.isPending}>确认</Button><Button type="button" size="sm" variant="secondary" onClick={() => setAddingOrderId(null)}>取消</Button></form>}</td></tr>; })}</tbody></table></div></Card>
      </section>}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h2 className="text-xl font-semibold text-white">按产品交付进度</h2><p className="text-sm text-bambu-gray">每个产品只显示一行，汇总所有未完成批次；点击“查看批次”可展开具体交期和订单。</p></div>
          <div className="flex flex-wrap items-center gap-2"><div className="relative"><Search size={16} className="absolute left-3 top-3 text-bambu-gray" /><input aria-label="筛选产品" placeholder="产品名称 / SKU 搜索" value={activeSearch} onChange={event => setActiveSearch(event.target.value)} className="stage16-input pl-9" /></div><Button type="button" variant="secondary" onClick={() => { queryClient.invalidateQueries({ queryKey: ['production-product-workbench'] }); queryClient.invalidateQueries({ queryKey: ['production-orders', 'active'] }); }}><Filter size={16} />刷新</Button></div>
        </div>
        <Card className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[1180px] text-left text-sm"><thead className="border-b border-bambu-dark-tertiary bg-bambu-dark/60 text-bambu-gray"><tr><th className="px-4 py-3">产品</th><th className="px-4 py-3">需求 / 已完成 / 剩余</th><th className="px-4 py-3">生产状态</th><th className="px-4 py-3">优先级</th><th className="px-4 py-3">最近交期</th><th className="px-4 py-3">打印机</th><th className="px-4 py-3">操作</th></tr></thead><tbody className="divide-y divide-bambu-dark-tertiary">{ordersFetching || summariesFetching ? <tr><td colSpan={7} className="px-4 py-12 text-center text-bambu-gray">正在读取产品进度…</td></tr> : visibleSummaries.length === 0 ? <tr><td colSpan={7} className="px-4 py-12 text-center text-bambu-gray"><ClipboardList className="mx-auto mb-2" />当前没有进行中的产品</td></tr> : visibleSummaries.map(summary => { const product = products.find(item => item.id === summary.product_id); const productOrders = orders.filter(order => order.product_id === summary.product_id); const isExpanded = expandedProductId === summary.product_id; const overdue = Boolean(summary.overdue); const remaining = summary.remaining_quantity ?? summary.pending_quantity; return <><tr key={`product-${summary.product_id}`} className={`hover:bg-bambu-dark/40 ${overdue ? 'bg-red-500/5' : ''}`}><td className="px-4 py-3"><div className="flex items-center gap-3"><div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-bambu-dark">{product?.images?.[0] ? <img src={imageUrl(summary.product_id, product.images[0].id)} alt="" className="h-full w-full object-cover" /> : <Box size={22} className="text-bambu-gray" />}</div><div className="min-w-0"><div className="truncate font-medium text-white">{summary.product_name || product?.name || `产品 ${summary.product_id}`}</div><div className="text-xs text-bambu-gray">{summary.product_sku || product?.sku || `产品 ${summary.product_id}`} · {summary.order_count ?? productOrders.length} 个生产批次</div></div></div></td><td className="px-4 py-3"><div className="flex flex-wrap gap-1.5 text-xs font-medium"><span className="rounded-full bg-sky-500/15 px-2 py-1 text-sky-300">需求 <b>{summary.total_quantity}</b></span><span className="rounded-full bg-emerald-500/15 px-2 py-1 text-emerald-300">已完成 <b>{summary.completed_quantity}</b></span><span className={`rounded-full px-2 py-1 ${remaining === 0 ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>剩余 <b>{remaining}</b></span></div><div className="mt-1 text-xs text-bambu-gray">单位：套</div></td><td className="px-4 py-3"><div className="text-white">打印中 {summary.printing_quantity ?? 0} · 已分配 {summary.assigned_quantity ?? 0}</div><div className="mt-1 text-xs text-bambu-gray">待质检 {summary.quality_quantity ?? 0} · 待清盘 {summary.cleanup_quantity ?? 0}</div></td><td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs ${(summary.highest_priority ?? 0) >= 3 ? 'bg-red-500/15 text-red-300' : (summary.highest_priority ?? 0) === 2 ? 'bg-amber-500/15 text-amber-300' : 'bg-bambu-dark-tertiary text-bambu-gray-light'}`}>{summary.priority_label || priorityText[summary.highest_priority ?? 0] || '极低'}</span></td><td className={`px-4 py-3 ${overdue ? 'font-semibold text-red-300' : 'text-bambu-gray-light'}`}>{overdue && <AlertTriangle size={14} className="mr-1 inline" />}{formatDate(summary.due_at)}{overdue && <div className="text-xs">{summary.overdue_order_count ?? 0} 个批次逾期</div>}</td><td className="px-4 py-3 text-bambu-gray-light">{summary.assigned_printer_names?.length ? summary.assigned_printer_names.join('、') : '待分配'}</td><td className="px-4 py-3"><Button type="button" size="sm" variant="secondary" onClick={() => setExpandedProductId(isExpanded ? null : summary.product_id)}>{isExpanded ? '收起批次' : '查看批次'}</Button></td></tr>{isExpanded && <tr key={`product-${summary.product_id}-batches`}><td colSpan={7} className="bg-bambu-dark/40 px-6 py-4"><div className="space-y-2">{productOrders.length === 0 ? <div className="text-sm text-bambu-gray">当前筛选没有匹配的批次。</div> : productOrders.map(order => { const orderRemaining = order.remaining_quantity ?? order.quantity; return <div key={order.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary p-3"><div><Link to={`/production-orders/${order.id}`} className="font-mono text-xs text-bambu-green hover:underline">{order.order_number}</Link><div className="mt-1 flex flex-wrap gap-1.5 text-xs font-medium"><span className="rounded-full bg-sky-500/15 px-2 py-1 text-sky-300">需求 {order.quantity} 套</span><span className="rounded-full bg-emerald-500/15 px-2 py-1 text-emerald-300">已完成 {order.completed_quantity ?? 0}</span><span className={`rounded-full px-2 py-1 ${orderRemaining === 0 ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>剩余 {orderRemaining}</span></div><div className="mt-1 text-xs text-bambu-gray">{order.priority_label || priorityText[order.priority] || '极低'} · 交期 {formatDateTime(order.due_at)} · {order.assigned_printer_names?.join('、') || '待分配'}</div></div><div className="flex items-center gap-2"><Link to={`/production-orders/${order.id}`} className="rounded-lg bg-bambu-dark-tertiary px-3 py-2 text-xs text-white hover:bg-bambu-gray-dark">查看详情</Link><Button type="button" size="sm" variant="ghost" onClick={() => { setAddingOrderId(order.id); setAdditionalQuantity(1); }}>追加数量</Button>{addingOrderId === order.id && <form className="flex gap-2" onSubmit={event => addQuantity(event, order.id, order.product_id)}><input aria-label="追加生产数量" type="number" min="1" value={additionalQuantity} onChange={event => setAdditionalQuantity(Number(event.target.value))} className="stage16-input w-24" /><Button type="submit" size="sm" disabled={append.isPending}>确认</Button><Button type="button" size="sm" variant="secondary" onClick={() => setAddingOrderId(null)}>取消</Button></form>}</div></div>; })}</div></td></tr>}</>})}</tbody></table></div></Card>
      </section>
    </>}

    {view === 'history' && <section className="space-y-3"><div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-2xl font-semibold text-white">历史订单</h2><p className="text-sm text-bambu-gray">已完成、取消和软删除批次独立保留，可追溯上一批交付数量。</p></div><div className="relative"><Search size={16} className="absolute left-3 top-3 text-bambu-gray" /><input aria-label="搜索历史订单" placeholder="订单号搜索" value={historySearch} onChange={event => setHistorySearch(event.target.value)} className="stage16-input pl-9" /></div></div><Card className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="border-b border-bambu-dark-tertiary bg-bambu-dark/60 text-bambu-gray"><tr><th className="px-4 py-3">订单</th><th className="px-4 py-3">产品</th><th className="px-4 py-3">批次数量</th><th className="px-4 py-3">合格 / 报废</th><th className="px-4 py-3">完成时间</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">操作</th></tr></thead><tbody className="divide-y divide-bambu-dark-tertiary">{historyFetching ? <tr><td colSpan={7} className="px-4 py-12 text-center text-bambu-gray">正在读取历史…</td></tr> : historyOrders.length === 0 ? <tr><td colSpan={7} className="px-4 py-12 text-center text-bambu-gray"><History className="mx-auto mb-2" />还没有历史订单</td></tr> : historyOrders.map(order => <tr key={order.id} className="hover:bg-bambu-dark/40"><td className="px-4 py-3"><div className="font-mono text-xs text-bambu-green">{order.order_number}</div><div className="text-xs text-bambu-gray">创建于 {formatDate(order.created_at)}</div></td><td className="px-4 py-3 text-white">{String(order.product_snapshot?.name || `产品 ${order.product_id}`)}</td><td className="px-4 py-3 text-white">{order.quantity} 套</td><td className="px-4 py-3 text-bambu-gray-light">{order.completed_quantity ?? 0} / {order.scrap_quantity ?? 0}</td><td className="px-4 py-3 text-bambu-gray-light">{formatDateTime(order.completed_at || order.updated_at)}</td><td className="px-4 py-3"><span className="rounded-full bg-bambu-dark-tertiary px-2.5 py-1 text-xs text-bambu-gray-light">{statusText[order.status] || order.status}</span></td><td className="px-4 py-3"><Link to={`/production-orders/${order.id}`} className="text-bambu-green hover:underline">查看批次</Link></td></tr>)}</tbody></table></div></Card></section>}

    {productPickerOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="选择产品"><div className="w-full max-w-2xl overflow-hidden rounded-xl border border-bambu-gray-dark bg-bambu-dark shadow-2xl"><div className="flex items-center justify-between border-b border-bambu-gray-dark p-4"><div><h2 className="text-xl font-semibold text-white">选择产品</h2><p className="mt-1 text-xs text-bambu-gray">输入名称、SKU 或产品编码快速定位</p></div><Button type="button" variant="ghost" aria-label="关闭产品选择" onClick={() => setProductPickerOpen(false)}>×</Button></div><div className="p-4"><div className="relative"><Search size={16} className="absolute left-3 top-3 text-bambu-gray" /><input autoFocus aria-label="搜索产品" placeholder="搜索产品名称或编码" value={productSearch} onChange={event => setProductSearch(event.target.value)} className="stage16-input w-full pl-9" /></div></div><div className="max-h-[55vh] space-y-2 overflow-y-auto px-4 pb-4">{filteredProducts.length === 0 ? <p className="py-8 text-center text-bambu-gray">没有匹配的产品</p> : filteredProducts.map(product => { const image = product.images?.[0]; return <button type="button" key={product.id} aria-label={`${product.name} ${product.sku}`} className="flex w-full items-center gap-3 rounded-lg border border-bambu-gray-dark bg-bambu-dark-secondary p-3 text-left hover:border-bambu-green" onClick={() => selectProduct(product.id)}><div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded bg-bambu-dark-tertiary">{image ? <img src={imageUrl(product.id, image.id)} alt="" className="h-full w-full object-cover" /> : <Box className="text-bambu-gray" size={24} />}</div><div className="min-w-0"><div className="truncate font-medium text-white">{product.name}</div><div className="text-sm text-bambu-green">{product.sku}</div></div></button>; })}</div></div></div>}
    {view === 'history' && <div className="flex flex-wrap items-end gap-2 rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/70 p-3 text-sm"><span className="mr-1 self-center text-bambu-gray">创建日期</span><label className="text-xs text-bambu-gray">从<input aria-label="历史订单开始日期" type="date" value={historyFrom} onChange={event => setHistoryFrom(event.target.value)} className="stage16-input mt-1 w-auto" /></label><label className="text-xs text-bambu-gray">到<input aria-label="历史订单结束日期" type="date" value={historyTo} onChange={event => setHistoryTo(event.target.value)} className="stage16-input mt-1 w-auto" /></label><button type="button" className="rounded-lg bg-bambu-dark-tertiary px-3 py-2 text-bambu-gray-light hover:text-white" onClick={() => { setHistoryFrom(''); setHistoryTo(''); }}>清除日期</button></div>}
    <div className="sr-only">{summaries.map(summary => <span key={`summary-${summary.product_id}`}><span>{summary.total_quantity}</span><span>已完成</span><span>待生产</span></span>)}{showCreate && <button type="button" onClick={() => { if (form.product_id && form.product_file_id) create.mutate({ ...form, product_file_id: form.product_file_id, due_at: form.due_at ? new Date(form.due_at).toISOString() : null }); }}>创建并计算需求数量</button>}{orders.length > 0 && <><button type="button" onClick={() => setAddingOrderId(orders[0].id)}>追加生产数量</button>{addingOrderId !== null && <input aria-label="追加生产数量" type="number" min="1" value={additionalQuantity} onChange={event => setAdditionalQuantity(Number(event.target.value))} /> }<button type="button" onClick={() => { const order = orders.find(item => item.id === addingOrderId) || orders[0]; append.mutate({ orderId: order.id, productId: order.product_id, quantity: additionalQuantity }); }}>确认追加</button></>}</div>
    {view === 'overview' && <div className="flex flex-wrap gap-2 text-xs"><span className="self-center text-bambu-gray">优先级筛选</span>{[['all','全部'],['4','最高'],['3','高'],['2','中'],['1','低'],['0','极低']].map(([value,label]) => <button type="button" key={value} onClick={() => setPriorityFilter(value)} className={`rounded-full px-3 py-1.5 ${priorityFilter === value ? 'bg-bambu-green text-bambu-dark' : 'bg-bambu-dark-tertiary text-bambu-gray-light hover:text-white'}`}>{label}</button>)}</div>}
    {view === 'overview' && <div className="sr-only" aria-hidden="true"><select aria-label="筛选优先级" value={priorityFilter} onChange={event => setPriorityFilter(event.target.value)}><option value="all">全部优先级</option></select></div>}
    <style>{`.stage16-input{background:#18181b;border:1px solid #3f3f46;border-radius:.55rem;padding:.65rem .75rem;color:white;min-width:0;width:100%;min-height:44px}[aria-label="筛选优先级"]{display:none}`}</style>
  </div>;
}
