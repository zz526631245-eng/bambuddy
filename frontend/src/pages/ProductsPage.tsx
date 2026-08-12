import { useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Box, Plus, Search, Upload } from 'lucide-react';
import { productsApi } from '../api/products';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { HubNav } from '../components/HubNav';
import { FileManagerPage } from './FileManagerPage';
import { MakerworldPage } from './MakerworldPage';

const imageUrl = (productId: number, imageId: number) => `/api/v1/products/${productId}/images/${imageId}/file`;

export function ProductsPage() {
  const queryClient = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ['products'], queryFn: productsApi.list });
  const [show, setShow] = useState(false);
  const [search, setSearch] = useState('');
  const [activeSection, setActiveSection] = useState('/products');
  const [form, setForm] = useState({ name: '', description: '', image: null as File | null, production_mode: 'single_plate' as 'single_plate' | 'multi_plate', source_plate_count: 1 });
  const create = useMutation({
    mutationFn: () => {
      if (!form.image) throw new Error('请先上传产品图片。');
      if (form.production_mode === 'multi_plate' && form.source_plate_count < 2) throw new Error('多盘产品至少需要 2 个源盘。');
      return productsApi.createWithImage(form.name, form.description, form.image, { production_mode: form.production_mode, source_plate_count: form.production_mode === 'multi_plate' ? form.source_plate_count : 1 });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['products'] }); setShow(false); setForm({ name: '', description: '', image: null, production_mode: 'single_plate', source_plate_count: 1 }); },
  });
  const importArchive = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file) return;
    try { await productsApi.importArchive(file); queryClient.invalidateQueries({ queryKey: ['products'] }); }
    catch (error) { window.alert(error instanceof Error ? error.message : '导入产品失败。'); }
  };
  const rows = data.filter(product => `${product.sku} ${product.name}`.toLowerCase().includes(search.toLowerCase()));
  const selectSection = (to: string) => setActiveSection(to);
  return <div className="p-4 md:p-8 max-w-[1500px] mx-auto space-y-6">
    <div className="flex flex-wrap gap-4 justify-between items-center"><div><h1 className="text-3xl font-bold text-white">产品资料</h1><p className="text-bambu-gray mt-1">产品编码由系统自动生成；创建产品时必须上传产品图片。</p></div><div className="flex gap-2"><label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-bambu-dark-tertiary text-white cursor-pointer"><Upload size={18} />导入产品包<input className="hidden" type="file" accept=".zip" onChange={importArchive} /></label><Button onClick={() => setShow(!show)}><Plus size={18} />新建产品</Button></div></div>
    <HubNav ariaLabel="产品资料相关功能" activeTo={activeSection} onSelect={selectSection} items={[
      { to: '/products', label: '产品资料' },
      { to: '/files', label: '文件管理器' },
      { to: '/makerworld', label: 'MakerWorld' },
    ]} />
    {activeSection !== '/products' && <section className="rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/30">
      {activeSection === '/files' && <FileManagerPage />}
      {activeSection === '/makerworld' && <MakerworldPage />}
    </section>}
    {activeSection === '/products' && <>
    {show && <Card><CardContent><form noValidate onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate(); }} className="grid md:grid-cols-3 gap-3">
      <input required placeholder="产品名称" value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" />
      <input placeholder="说明（可不填）" value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" />
      <label className="flex items-center gap-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white cursor-pointer"><Upload size={17} />{form.image ? form.image.name : '选择产品图片（必填）'}<input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={event => setForm({ ...form, image: event.target.files?.[0] || null })} /></label>
      <label className="block text-sm text-bambu-gray">产品生产结构<select aria-label="产品生产结构" value={form.production_mode} onChange={event => setForm({ ...form, production_mode: event.target.value as 'single_plate' | 'multi_plate', source_plate_count: event.target.value === 'multi_plate' ? Math.max(2, form.source_plate_count) : 1 })} className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white"><option value="single_plate">单盘产品（一盘完成一套）</option><option value="multi_plate">多盘产品（多盘完成一套）</option></select></label>
      {form.production_mode === 'multi_plate' && <label className="block text-sm text-bambu-gray">几盘打印一套产品<input aria-label="几盘打印一套产品" type="number" min="2" step="1" value={form.source_plate_count} onChange={event => setForm({ ...form, source_plate_count: Number(event.target.value) })} className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" /><span className="text-xs">例如输入 3，产品详情会显示 3 个源文件上传位置。</span></label>}
      <div className="md:col-span-3 flex items-center gap-3"><Button type="submit" disabled={create.isPending}>{create.isPending ? '创建中…' : '创建产品'}</Button><span className="text-sm text-bambu-gray">产品编码会自动生成，例如 PRD-0001</span></div>
      {create.error && <p role="alert" className="text-red-400 md:col-span-3">{create.error instanceof Error ? create.error.message : '产品创建失败。'}</p>}
    </form></CardContent></Card>}
    <div className="relative max-w-md"><Search className="absolute left-3 top-2.5 text-bambu-gray" size={18} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索产品编码或产品名" className="w-full bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg pl-10 pr-3 py-2 text-white" /></div>
    {rows.length === 0 ? <Card><CardContent className="text-center text-bambu-gray py-16"><Box className="mx-auto mb-3" />还没有产品，点击“新建产品”开始。</CardContent></Card> : <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">{rows.map(product => { const image = product.images?.[0]; return <Link key={product.id} to={`/products/${product.id}`}><Card className="h-full hover:border-bambu-green transition-colors overflow-hidden"><div className="aspect-video bg-bambu-dark flex items-center justify-center">{image ? <img src={imageUrl(product.id, image.id)} alt={product.name} className="w-full h-full object-cover" /> : <Box className="text-bambu-gray" size={42} />}</div><CardContent><div className="flex justify-between"><span className="text-xs px-2 py-1 rounded bg-bambu-green/20 text-bambu-green">{product.sku}</span><span className={product.is_active ? 'text-green-400' : 'text-bambu-gray'}>{product.is_active ? '启用' : '停用'}</span></div><h2 className="text-xl text-white font-semibold mt-4">{product.name}</h2><p className="text-bambu-gray mt-2 line-clamp-2">{product.description || '暂无说明'}</p><p className="text-bambu-green mt-5">查看产品详情 →</p></CardContent></Card></Link>; })}</div>}
    </>}
  </div>;
}
