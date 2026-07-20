import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Ban, CheckCircle2, Download, Pause, Play, RefreshCw, ScrollText, Trash2, XCircle } from 'lucide-react';
import { productionApi, type PlateJob, type PlateJobPreviewItem } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';

const statusText: Record<string, string> = {
  draft: '草稿', planned: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消',
  pending: '等待安排', in_progress: '生产中', assigned: '已分配', printing: '打印中',
  succeeded: '切片成功', failed: '切片失败', slicing: '切片中',
};

const operationText: Record<string, string> = {
  production_order_created: '创建生产订单', production_order_paused: '暂停订单',
  production_order_resumed: '恢复订单', production_order_cancelled: '取消订单',
  plate_jobs_confirmed: '确认打印任务', production_plate_job_allocated: '自动分配打印任务',
  production_plate_job_cancelled: '取消打印任务',
};

type SlicePlate = { slice_artifact_id: number; output_file_name?: string; plate_quantity?: number };

function SliceJobRow({
  job, onRetry, onRealSlice, onCancel, onDelete, onDownload,
}: {
  job: PlateJob;
  onRetry: (id: number) => void;
  onRealSlice: (id: number) => void;
  onCancel: (id: number) => void;
  onDelete: (id: number) => void;
  onDownload: (id: number) => void;
}) {
  const result = job.slice_result;
  const plates = Array.isArray(result?.plates)
    ? result.plates.filter((plate): plate is SlicePlate => typeof plate === 'object' && plate !== null && typeof plate.slice_artifact_id === 'number')
    : [];
  const isTerminal = ['cancelled', 'completed'].includes(job.status);
  return <div className="rounded-lg border border-bambu-dark-tertiary p-3 space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-2 text-white">
      <span>打印任务 #{job.id} · 本盘 {job.planned_quantity} 套</span>
      <span className={job.status === 'printing' ? 'text-blue-300' : job.status === 'cancelled' ? 'text-gray-400' : job.slice_status === 'succeeded' ? 'text-bambu-green' : job.slice_status === 'failed' ? 'text-red-400' : 'text-amber-300'}>{statusText[job.status] || job.status} / {statusText[job.slice_status] || job.slice_status}</span>
    </div>
    <div className="text-sm text-bambu-gray space-y-1">
      <div>{job.virtual_printer_name ? `虚拟打印机：${job.virtual_printer_name}` : job.virtual_printer_id ? `虚拟打印机 #${job.virtual_printer_id}` : '尚未分配虚拟打印机'} · {job.printer_profile_name ? `打印机：${job.printer_profile_name}` : job.printer_profile_id ? `打印机配置 #${job.printer_profile_id}` : '尚未分配打印机配置'}{job.printer_model ? ` · 型号 ${job.printer_model}` : ''}{job.queue_item_id ? ` · 队列任务 #${job.queue_item_id}${job.queue_status ? `（${statusText[job.queue_status] || job.queue_status}）` : ''}` : ''}</div>
      {typeof result?.plate_count === 'number' && <div>切片盘数：{result.plate_count} · 每盘数量：{Array.isArray(result.plate_quantities) ? result.plate_quantities.join('、') : '—'}</div>}
    </div>
    {job.slice_error && <p role="alert" className="text-sm text-red-400">{job.slice_error}</p>}
    {plates.length > 0 && <div className="space-y-1 text-sm"><div className="text-bambu-gray">切好的打印文件盘：</div>{plates.map(plate => <div key={plate.slice_artifact_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-bambu-dark-secondary px-2 py-1 text-white"><span>{plate.output_file_name || `切片文件 #${plate.slice_artifact_id}`}{typeof plate.plate_quantity === 'number' ? ` · 一盘 ${plate.plate_quantity} 套` : ''}</span><Button type="button" variant="secondary" size="sm" onClick={() => onDownload(plate.slice_artifact_id)}><Download size={14} />下载</Button></div>)}</div>}
    <div className="flex flex-wrap gap-2">
      {job.slice_status === 'failed' && <Button type="button" variant="secondary" size="sm" onClick={() => onRetry(job.id)}><RefreshCw size={15} />重试切片</Button>}
      {job.slice_status !== 'slicing' && <Button type="button" size="sm" onClick={() => onRealSlice(job.id)}><RefreshCw size={15} />运行真实切片</Button>}
      {!isTerminal && <Button type="button" variant="danger" size="sm" onClick={() => window.confirm('确定取消这个打印任务吗？') && onCancel(job.id)}><XCircle size={15} />取消此打印任务</Button>}
      {job.status !== 'printing' && <Button type="button" variant="secondary" size="sm" onClick={() => window.confirm('确定删除这个打印任务吗？') && onDelete(job.id)}><Trash2 size={15} />删除此打印任务</Button>}
    </div>
  </div>;
}

export function ProductionOrderDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['production-order', id] });
  const { data: order, isLoading } = useQuery({ queryKey: ['production-order', id], queryFn: () => productionApi.getOrder(id) });
  const [preview, setPreview] = useState<PlateJobPreviewItem[] | null>(null);
  const state = useMutation({ mutationFn: (action: 'pause' | 'resume') => productionApi.changeStatus(id, action), onSuccess: () => { refresh(); queryClient.invalidateQueries({ queryKey: ['production-orders'] }); } });
  const cancelOrder = useMutation({ mutationFn: () => productionApi.cancelOrder(id), onSuccess: () => { refresh(); queryClient.invalidateQueries({ queryKey: ['production-orders'] }); } });
  const deleteOrder = useMutation({ mutationFn: () => productionApi.deleteOrder(id), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['production-orders'] }); navigate('/production-orders'); } });
  const previewJobs = useMutation({ mutationFn: () => productionApi.previewJobs(id), onSuccess: result => setPreview(result.items) });
  const confirmJobs = useMutation({ mutationFn: (items: PlateJobPreviewItem[]) => productionApi.confirmJobs(id, items), onSuccess: () => { setPreview(null); refresh(); } });
  const retrySlice = useMutation({ mutationFn: (jobId: number) => productionApi.retrySlice(jobId), onSuccess: refresh });
  const realSlice = useMutation({ mutationFn: (jobId: number) => productionApi.realSlice(jobId), onSuccess: refresh });
  const cancelJob = useMutation({ mutationFn: (jobId: number) => productionApi.cancelPlateJob(jobId), onSuccess: refresh });
  const deleteJob = useMutation({ mutationFn: (jobId: number) => productionApi.deletePlateJob(jobId), onSuccess: refresh });

  if (isLoading || !order) return <div className="p-8 text-white">加载中…</div>;
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <Link to="/production-orders" className="text-bambu-gray hover:text-white flex gap-2"><ArrowLeft size={18} />返回生产订单</Link>
    <div className="flex flex-wrap justify-between gap-4"><div><div className="font-mono text-bambu-green">{order.order_number}</div><h1 className="text-3xl text-white font-bold">{String(order.product_snapshot?.name || '生产订单')}</h1><p className="text-bambu-gray">生产 {order.quantity} 套 · 优先级 {order.priority} · {statusText[order.status] || order.status}</p></div><div className="flex gap-2">{order.status === 'planned' && <Button variant="secondary" onClick={() => state.mutate('pause')}><Pause size={16} />暂停</Button>}{order.status === 'paused' && <Button onClick={() => state.mutate('resume')}><Play size={16} />恢复</Button>}{!['cancelled', 'completed'].includes(order.status) && <Button variant="danger" onClick={() => window.confirm('确定取消这个订单吗？') && cancelOrder.mutate()}><Ban size={16} />取消整个打印任务</Button>}<Button variant="secondary" onClick={() => window.confirm('确定删除整个生产订单及其打印任务吗？') && deleteOrder.mutate()}><Trash2 size={16} />删除整个打印任务</Button></div></div>
    {(deleteOrder.error || cancelOrder.error || cancelJob.error || deleteJob.error) && <p role="alert" className="text-red-400">{String((deleteOrder.error || cancelOrder.error || cancelJob.error || deleteJob.error) as Error)}</p>}
    <Card><CardHeader><div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl text-white font-semibold">数量与完成进度</h2><p className="text-sm text-bambu-gray">这里显示每个打印盘的切片文件、切片状态、打印状态和分配的打印机。</p></div>{order.status === 'planned' && <Button onClick={() => previewJobs.mutate()}>预览打印任务草稿</Button>}</div></CardHeader>
      <CardContent className="space-y-4">{order.requirements.map(requirement => { const component = String(requirement.component_snapshot?.name || `需求 ${requirement.component_id ?? ''}`); return <div key={requirement.id} className="p-4 rounded-lg bg-bambu-dark space-y-3"><div className="flex justify-between"><div><h3 className="text-white font-semibold">{component}</h3><p className="text-sm text-bambu-gray">{String(requirement.recipe_snapshot?.name || '产品源文件')} · 每套需要 {requirement.unit_quantity}</p></div><span className="text-bambu-gray">{statusText[requirement.status] || requirement.status}</span></div><div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center">{[['计划数量', requirement.ledger.planned], ['已安排', requirement.ledger.reserved], ['合格', requirement.ledger.good], ['报废', requirement.ledger.scrap], ['剩余', requirement.ledger.remaining]].map(([label, value]) => <div key={String(label)} className="rounded bg-bambu-dark-secondary p-3"><div className="text-xs text-bambu-gray">{label}</div><div className="text-xl text-white">{value}</div></div>)}</div><div className="space-y-2">{requirement.plate_jobs.length ? requirement.plate_jobs.map(job => <SliceJobRow key={job.id} job={job} onRetry={jobId => retrySlice.mutate(jobId)} onRealSlice={jobId => realSlice.mutate(jobId)} onCancel={jobId => cancelJob.mutate(jobId)} onDelete={jobId => deleteJob.mutate(jobId)} onDownload={artifactId => productionApi.downloadSliceArtifact(artifactId)} />) : <p className="text-sm text-bambu-gray">尚未确认打印任务。</p>}</div></div>; })}</CardContent>
    </Card>
    {preview && <Card><CardHeader><h2 className="text-xl text-white font-semibold">确认并自动分配打印任务</h2></CardHeader><CardContent className="space-y-4"><p className="text-bambu-gray">确认后会按产品源文件策略生成切片并匹配虚拟打印机，不会发送真实打印。</p>{preview.length === 0 ? <p className="text-white">当前没有剩余数量需要安排。</p> : preview.map(item => <div key={item.requirement_id} className="flex justify-between bg-bambu-dark rounded p-3 text-white"><span>{item.component_name} · {item.print_plan_name}</span><span>安排 {item.planned_quantity} 套</span></div>)}<div className="flex gap-2"><Button variant="secondary" onClick={() => setPreview(null)}>返回修改</Button><Button disabled={!preview.length || confirmJobs.isPending} onClick={() => confirmJobs.mutate(preview)}><CheckCircle2 size={16} />确认并自动分配</Button></div>{confirmJobs.error && <p className="text-red-400">{String(confirmJobs.error)}</p>}</CardContent></Card>}
    <Card><CardHeader><h2 className="text-xl text-white font-semibold flex gap-2"><ScrollText />操作记录</h2></CardHeader><CardContent><div className="space-y-3">{order.operations.map(operation => <div key={operation.id} className="border-l-2 border-bambu-green pl-4"><div className="text-white">{operationText[operation.operation_type] || operation.operation_type}</div><div className="text-xs text-bambu-gray">{new Date(operation.created_at).toLocaleString()}</div></div>)}</div></CardContent></Card>
  </div>;
}
