import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Download, ImagePlus } from 'lucide-react';
import { productsApi, type Product } from '../api/products';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';

function ProductImagePreview({ productId, image }: { productId: number; image: { id: number; original_name: string } }) {
  const { data } = useQuery({ queryKey: ['product-image', productId, image.id], queryFn: () => productsApi.getImageBlob(productId, image.id) });
  const url = useMemo(() => (data ? URL.createObjectURL(data) : ''), [data]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  return url ? <img src={url} alt={image.original_name} className="aspect-square object-cover rounded-lg bg-bambu-dark" /> : <div className="aspect-square rounded-lg bg-bambu-dark animate-pulse" />;
}

function ProductFileCard({ productId, product, refresh }: { productId: number; product: Product; refresh: () => void }) {
  const [strategy, setStrategy] = useState<'fixed_plate' | 'auto_pack'>('fixed_plate');
  const [units, setUnits] = useState(1);
  const [material, setMaterial] = useState('PETG');
  const [color, setColor] = useState('黑色');
  const [productColor, setProductColor] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<Array<File | null>>([]);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const chooseFile = (event: ChangeEvent<HTMLInputElement>, index = 0) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.3mf')) {
      setError('请选择 .3mf 源文件');
      return;
    }
    setError(null);
    setSuccess(null);
    setSelectedFiles(previous => { const next = [...previous]; next[index] = file; return next; });
    setShowUploadDialog(true);
  };

  const closeUploadDialog = () => {
    if (uploading) return;
    setShowUploadDialog(false);
    setSelectedFiles([]);
  };

  const upload = async () => {
    const files = product.production_mode === 'multi_plate' ? selectedFiles : [selectedFiles[0]];
    if (files.some(file => !file)) {
      setError(`请为这套产品选择 ${product.production_mode === 'multi_plate' ? product.source_plate_count : 1} 个源 3MF 文件`);
      return;
    }
    if (product.production_mode !== 'multi_plate' && (!Number.isFinite(units) || units < 1)) {
      setError('一盘预计生产套数必须是至少 1 的数字');
      return;
    }
    if (!material.trim() || !color.trim()) {
      setError('请填写文件需要的材料和颜色');
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const sourceSetId = product.production_mode === 'multi_plate' ? crypto.randomUUID() : undefined;
      for (let index = 0; index < files.length; index += 1) {
        await productsApi.uploadProductFile(productId, files[index]!, {
          strategy,
          units_per_plate: product.production_mode === 'multi_plate' ? 1 : units,
          component_ids: [],
          compatible_printer_models: [],
          filament_requirements: [{ slot: 0, material: material.trim().toUpperCase(), color: color.trim() }],
          product_color: productColor.trim() || undefined,
          source_set_id: sourceSetId,
          source_plate_index: product.production_mode === 'multi_plate' ? index : 0,
        });
      }
      refresh();
      setSuccess(`已上传 ${files.length} 个源文件；已有订单需要重新计算`);
      closeUploadDialog();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '上传失败，请稍后重试');
    } finally {
      setUploading(false);
    }
  };

  const removeFile = async (fileId: number) => {
    if (!window.confirm('确定彻底删除这个产品源文件吗？有历史订单引用时只能停用。')) return;
    try {
      await productsApi.deleteProductFile(productId, fileId);
      refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '删除失败，请先停用或检查历史订单引用');
    }
  };

  const deactivateFile = async (fileId: number) => {
    if (!window.confirm('停用后旧订单会保留快照，但不能继续执行。确定停用吗？')) return;
    try {
      await productsApi.deactivateProductFile(productId, fileId);
      refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '停用失败，请稍后重试');
    }
  };

  const files = product.product_files ?? [];
  const multiSlots = Array.from({ length: product.source_plate_count }, (_, index) => index);

  return <>
    <Card>
      <CardHeader>
        <div>
          <h2 className="text-xl font-semibold text-white">产品源文件</h2>
          <p className="text-sm text-bambu-gray mt-1">上传属于本产品的源 3MF。点击上传后填写材料、颜色和摆盘信息。</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-bambu-dark-tertiary p-4">
          <p className="text-sm text-bambu-gray">{product.production_mode === 'multi_plate' ? `这是多盘产品，一套需要 ${product.source_plate_count} 个源文件；每个源文件对应一张源盘。` : '每个文件可以代表一种产品颜色或零件颜色；同一颜色再次上传会生成新版本并停用旧版本。'}</p>
          {product.production_mode === 'single_plate' ? <><label htmlFor="product-source-file" className={`inline-flex items-center justify-center font-medium rounded-lg px-4 py-2 text-sm gap-2 min-h-[44px] bg-bambu-green hover:bg-bambu-green-light text-white cursor-pointer ${uploading ? 'opacity-50 pointer-events-none' : ''}`}>上传源 3MF</label><input id="product-source-file" type="file" accept=".3mf" className="sr-only" onChange={chooseFile} disabled={uploading} /></> : <Button type="button" onClick={() => { setSelectedFiles(Array.from({ length: product.source_plate_count }, () => null)); setShowUploadDialog(true); }} disabled={uploading}>上传这套源文件</Button>}
        </div>
        {error && <p role="alert" className="text-red-400">{error}</p>}
        {success && <p role="status" className="text-bambu-green">{success}</p>}
        <div className="divide-y divide-bambu-dark-tertiary">
          {!files.length ? <p className="text-bambu-gray">还没有产品源文件。</p> : files.map(file => <div key={file.id} className={`py-3 flex flex-wrap items-center justify-between gap-2 ${file.is_active ? 'text-white' : 'text-bambu-gray opacity-75'}`}>
            <span>{file.name} · {product.production_mode === 'multi_plate' ? `源盘 ${file.source_plate_index + 1}/${product.source_plate_count}` : `v${file.version}`} · {file.is_active ? '启用' : '已停用'}</span>
            <span>{file.product_color || '未命名颜色'} · {product.production_mode === 'multi_plate' ? '多盘产品 · 每盘 1 份' : file.strategy === 'auto_pack' ? '自动摆盘' : '固定摆盘'} · {product.production_mode === 'multi_plate' ? `第 ${file.source_plate_index + 1} 盘` : `每盘 ${file.units_per_plate} 套`}</span>
            <span className="text-xs">材料/颜色：{(Array.isArray(file.filament_requirements) ? file.filament_requirements : []).map(requirement => `${requirement.material} ${requirement.color}`).join('、') || '未设置'}</span>
            <div className="flex gap-2">
              {file.is_active && <Button type="button" variant="secondary" size="sm" onClick={() => deactivateFile(file.id)}>停用</Button>}
              <Button type="button" variant="danger" size="sm" onClick={() => removeFile(file.id)}>删除</Button>
            </div>
          </div>)}
        </div>
      </CardContent>
    </Card>
    {showUploadDialog && selectedFiles.length > 0 && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="upload-product-file-title">
      <Card className="w-full max-w-xl">
        <CardHeader><div><h3 id="upload-product-file-title" className="text-xl font-semibold text-white">填写产品源文件信息</h3><p className="text-sm text-bambu-gray mt-1">{product.production_mode === 'multi_plate' ? `共 ${product.source_plate_count} 张源盘，上传后会作为一套产品` : selectedFiles[0]?.name}</p></div></CardHeader>
        <CardContent className="space-y-4">
          {product.production_mode === 'multi_plate' ? <div className="space-y-2 rounded-lg border border-bambu-green/40 bg-bambu-dark p-3 text-sm text-bambu-gray">{multiSlots.map(index => <label key={index} className="flex items-center justify-between gap-3">源盘 {index + 1}<input type="file" accept=".3mf" onChange={event => chooseFile(event, index)} disabled={uploading} className="block w-2/3 text-xs" />{selectedFiles[index] && <span className="text-bambu-green">已选择</span>}</label>)}<p>每张源盘只打印 1 份，全部源盘完成才算 1 套产品；系统不会自动摆盘。</p></div> : <><label className="block text-sm text-bambu-gray">文件模式<select aria-label="摆盘方式" value={strategy} onChange={event => setStrategy(event.target.value as 'fixed_plate' | 'auto_pack')} className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white"><option value="fixed_plate">固定摆盘（只切片）</option><option value="auto_pack">自动摆盘（一盘多套）</option></select></label><label className="block text-sm text-bambu-gray">一盘预计生产套数<input aria-label="一盘预计生产套数" title="一盘能产出多少套完整产品，不是订单总数" type="number" min="1" step="1" value={units} onChange={event => setUnits(Number(event.target.value))} className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" /></label></>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block text-sm text-bambu-gray">材料<input aria-label="产品文件材料" value={material} onChange={event => setMaterial(event.target.value)} placeholder="例如 PETG" className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" /></label>
            <label className="block text-sm text-bambu-gray">文件颜色<input aria-label="产品文件颜色" value={color} onChange={event => setColor(event.target.value)} placeholder="例如 白色 或 #FFFFFF" className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" /></label>
          </div>
          <label className="block text-sm text-bambu-gray">产品颜色/变体（可选）<input aria-label="产品文件产品颜色变体" value={productColor} onChange={event => setProductColor(event.target.value)} placeholder="例如 红色盖子" className="mt-1 block w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white" /></label>
          {error && <p role="alert" className="text-red-400">{error}</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={closeUploadDialog} disabled={uploading}>取消</Button><Button type="button" onClick={upload} disabled={uploading}>{uploading ? '上传中…' : '确认上传'}</Button></div>
        </CardContent>
      </Card>
    </div>}
  </>;
}

export function ProductDetailPage() {
  const id = Number(useParams().id);
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['product', id] });
  const { data: product, isLoading } = useQuery({ queryKey: ['product', id], queryFn: () => productsApi.get(id) });
  const updateSizeClass = useMutation({ mutationFn: (sizeClass: 'standard' | 'large') => productsApi.update(id, { size_class: sizeClass }), onSuccess: refresh });
  const updateStructure = useMutation({ mutationFn: (data: { production_mode: 'single_plate' | 'multi_plate'; source_plate_count: number }) => productsApi.update(id, data), onSuccess: refresh });
  const exportProduct = useMutation({ mutationFn: () => productsApi.exportArchive(id), onSuccess: ({ blob, filename }) => { const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url); } });
  const uploadImage = async (event: ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) { await productsApi.uploadImage(id, file); refresh(); } };
  if (isLoading || !product) return <div className="p-8 text-white">加载中…</div>;
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <Link to="/products" className="text-bambu-gray hover:text-white flex gap-2"><ArrowLeft size={18} />返回产品列表</Link>
    <div className="flex flex-wrap justify-between gap-3"><div><div className="text-bambu-green font-mono">{product.sku}</div><h1 className="text-3xl font-bold text-white">{product.name}</h1><p className="text-bambu-gray">{product.description || '暂无说明'}</p></div><Button variant="secondary" disabled={exportProduct.isPending} onClick={() => exportProduct.mutate()}><Download size={18} />导出完整产品包</Button></div>
    <Card><CardContent className="space-y-3"><div className="flex flex-wrap gap-4 items-center"><label className="inline-flex items-center gap-2 text-sm text-bambu-gray">模型尺寸<select aria-label="产品模型尺寸" value={product.size_class} onChange={event => updateSizeClass.mutate(event.target.value as 'standard' | 'large')} disabled={updateSizeClass.isPending} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-2 py-1 text-white"><option value="standard">普通尺寸（可用 A1/A2L）</option><option value="large">大尺寸（排除 A1）</option></select></label><label className="inline-flex items-center gap-2 text-sm text-bambu-gray">产品生产结构<select aria-label="产品生产结构" value={product.production_mode} onChange={event => { const mode = event.target.value as 'single_plate' | 'multi_plate'; updateStructure.mutate({ production_mode: mode, source_plate_count: mode === 'multi_plate' ? Math.max(2, product.source_plate_count) : 1 }); }} disabled={updateStructure.isPending} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-2 py-1 text-white"><option value="single_plate">单盘产品（一盘完成一套）</option><option value="multi_plate">多盘产品（多盘完成一套）</option></select></label>{product.production_mode === 'multi_plate' && <label className="inline-flex items-center gap-2 text-sm text-bambu-gray">一套源盘数量<input aria-label="一套源盘数量" type="number" min="2" step="1" defaultValue={product.source_plate_count} onBlur={event => { const count = Number(event.target.value); if (Number.isInteger(count) && count >= 2 && count !== product.source_plate_count) updateStructure.mutate({ production_mode: 'multi_plate', source_plate_count: count }); }} className="w-20 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-2 py-1 text-white" /></label>}</div><p className="text-xs text-bambu-gray">大尺寸标签只用于自动分配排除 A1；产品生产结构决定一套产品需要几张源盘。修改结构后，已有订单会标记为需要重新计算。</p></CardContent></Card>
    <ProductFileCard productId={id} product={product} refresh={refresh} />
    <Card><CardHeader><div className="flex justify-between"><h2 className="text-xl font-semibold text-white">产品图片</h2><label className="cursor-pointer text-bambu-green flex gap-2"><ImagePlus size={18} />上传图片<input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={uploadImage} /></label></div></CardHeader><CardContent>{!product.images?.length ? <p className="text-bambu-gray">暂无图片（支持 PNG/JPEG/WebP，最大 10MB）</p> : <div className="grid grid-cols-2 md:grid-cols-5 gap-3">{product.images.map(image => <ProductImagePreview key={image.id} productId={id} image={image} />)}</div>}</CardContent></Card>
  </div>;
}
