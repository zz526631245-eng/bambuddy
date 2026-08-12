import * as React from 'react';
import { BrowserQRCodeReader, type IScannerControls } from '@zxing/browser';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft, Box, CheckCircle2, ChevronRight, CircleHelp, ClipboardCheck,
  Factory, Gauge, PackageCheck, PackageMinus, QrCode, ScanLine, Settings,
  Trash2, Wrench, X,
} from 'lucide-react';
import { ApiError, getMobileServerUrl, normalizeServerUrl, setMobileServerUrl } from '../api/client';
import { productionApi, type PlateJob, type PrinterConsumableTarget } from '../api/production';
import { useAuth } from '../contexts/AuthContext';

type Action = 'receive' | 'change' | 'deplete' | 'scrap' | 'quality' | 'cleanup';
type ParsedQr = { code: string; targetKey?: string; material?: string; colorHex?: string; colorName?: string };

const actionMeta: Record<Action, { title: string; description: string; icon: typeof Box; color: string }> = {
  receive: { title: '耗材入库', description: '扫描卷料二维码，登记到库存', icon: PackageCheck, color: 'from-emerald-500 to-teal-500' },
  change: { title: '打印机换料', description: '先扫打印机，再扫耗材卷', icon: Wrench, color: 'from-blue-500 to-cyan-500' },
  deplete: { title: '耗材用完', description: '扫描二维码标记为已用完', icon: PackageMinus, color: 'from-amber-500 to-orange-500' },
  scrap: { title: '耗材报废', description: '扫描二维码记录报废', icon: Trash2, color: 'from-rose-500 to-red-500' },
  quality: { title: '打印质检', description: '填写本盘合格数量', icon: ClipboardCheck, color: 'from-violet-500 to-purple-500' },
  cleanup: { title: '清理料盘', description: '确认清板后释放打印机', icon: Gauge, color: 'from-indigo-500 to-blue-500' },
};

function parseQr(raw: string): ParsedQr {
  const value = raw.trim();
  try {
    const url = new URL(value);
    const targetKey = url.searchParams.get('printer') || undefined;
    const nested = url.searchParams.get('scan');
    if (nested) return { ...parseQr(nested), ...(targetKey ? { targetKey } : {}) };
    if (url.protocol === 'bambuddy:') {
      return {
        code: url.searchParams.get('code') || value,
        targetKey,
        material: url.searchParams.get('material') || undefined,
        colorHex: url.searchParams.get('color') || undefined,
        colorName: url.searchParams.get('name') || undefined,
      };
    }
    if (targetKey) return { code: '', targetKey };
  } catch {
    // A plain CU-... value is the normal label format.
  }
  return { code: value };
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

function MobileScanner({ onDecoded, onClose }: { onDecoded: (value: string) => void; onClose: () => void }) {
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const controlsRef = React.useRef<IScannerControls | null>(null);
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    let stopped = false;
    const reader = new BrowserQRCodeReader();
    const start = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError('当前设备不支持摄像头，请使用扫码枪或手动输入。');
        return;
      }
      try {
        if (!videoRef.current) return;
        controlsRef.current = await reader.decodeFromConstraints(
          { video: { facingMode: { ideal: 'environment' } }, audio: false },
          videoRef.current,
          result => {
            const value = result?.getText();
            if (!stopped && value) {
              stopped = true;
              controlsRef.current?.stop();
              onDecoded(value);
            }
          },
        );
      } catch {
        setError('无法打开摄像头，请在系统设置中允许 Bambuddy 使用相机。');
      }
    };
    void start();
    return () => { stopped = true; controlsRef.current?.stop(); controlsRef.current = null; };
  }, [onDecoded]);
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/85 p-5">
    <div className="w-full max-w-md overflow-hidden rounded-3xl border border-white/10 bg-[#192126] shadow-2xl">
      <div className="flex items-center justify-between px-5 py-4"><div className="flex items-center gap-2 text-white"><ScanLine size={20} className="text-emerald-400" /><span className="font-semibold">对准二维码</span></div><button type="button" aria-label="关闭扫码" onClick={onClose} className="rounded-full p-2 text-slate-300 hover:bg-white/10"><X size={20} /></button></div>
      <div className="relative mx-5 overflow-hidden rounded-2xl bg-black"><video ref={videoRef} muted playsInline className="aspect-square w-full object-cover" /><div className="pointer-events-none absolute inset-8 rounded-2xl border-2 border-emerald-400/80" /><div className="pointer-events-none absolute inset-x-12 top-1/2 h-0.5 bg-emerald-400/80" /></div>
      <p className="px-5 py-4 text-center text-sm text-slate-400">保持二维码在框内，识别成功后会自动进入下一步。</p>
      {error && <p className="px-5 pb-4 text-center text-sm text-rose-300">{error}</p>}
    </div>
  </div>;
}

function ServerSetup({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = React.useState(getMobileServerUrl());
  const [error, setError] = React.useState('');
  const save = () => {
    const normalized = normalizeServerUrl(value);
    if (!/^https?:\/\//i.test(normalized)) { setError('请输入完整地址，例如 https://192.168.1.20:8019'); return; }
    setMobileServerUrl(normalized);
    onSaved();
  };
  return <div className="flex min-h-screen items-center justify-center bg-[#10171b] p-6 text-white"><div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#192126] p-7 shadow-2xl"><div className="mb-6 flex items-center gap-3"><div className="rounded-2xl bg-emerald-500/15 p-3 text-emerald-400"><Factory size={28} /></div><div><h1 className="text-2xl font-bold">连接 Bambuddy</h1><p className="mt-1 text-sm text-slate-400">手机 App 连接电脑上的同一台服务器</p></div></div><label className="text-sm text-slate-300">服务器 HTTPS 地址<input autoFocus value={value} onChange={event => setValue(event.target.value)} placeholder="https://192.168.1.20:8019" className="mt-2 w-full rounded-2xl border border-white/10 bg-[#10171b] px-4 py-3 text-white outline-none focus:border-emerald-400" /></label><p className="mt-3 text-xs leading-5 text-slate-500">电脑和手机需要在同一局域网。使用 HTTPS 才能打开摄像头；自签名证书首次需要在手机浏览器中信任。</p>{error && <p className="mt-3 text-sm text-rose-300">{error}</p>}<button type="button" onClick={save} className="mt-6 w-full rounded-2xl bg-emerald-500 px-4 py-3.5 font-semibold text-slate-950 hover:bg-emerald-400">连接服务器</button></div></div>;
}

function JobPicker({ action, jobs, onDone, onBack }: { action: 'quality' | 'cleanup'; jobs: PlateJob[]; onDone: () => void; onBack: () => void }) {
  const [selectedId, setSelectedId] = React.useState<number | null>(null);
  const [good, setGood] = React.useState(0);
  const queryClient = useQueryClient();
  const selected = jobs.find(job => job.id === selectedId);
  React.useEffect(() => { if (selected) setGood(selected.planned_quantity); }, [selected]);
  const mutation = useMutation({ mutationFn: () => productionApi.advanceWorkflow(selected!.id, action, action === 'quality' ? { good_quantity: good } : undefined), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['mobile-plate-jobs'] }); onDone(); } });
  return <div className="space-y-4"><div className="flex items-center justify-between"><button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-slate-400"><ArrowLeft size={16} />返回</button><span className="text-sm text-slate-400">选择任务</span></div>{jobs.length === 0 ? <div className="rounded-2xl border border-white/10 bg-[#192126] p-6 text-center text-slate-400">当前没有需要{action === 'quality' ? '质检' : '清板'}的任务。</div> : <div className="space-y-2">{jobs.map(job => <button type="button" key={job.id} onClick={() => setSelectedId(job.id)} className={`w-full rounded-2xl border p-4 text-left transition ${selectedId === job.id ? 'border-emerald-400 bg-emerald-400/10' : 'border-white/10 bg-[#192126] hover:border-white/30'}`}><div className="flex items-center justify-between text-white"><span>打印任务 #{job.id}</span><span className="text-sm text-emerald-300">{action === 'quality' ? `本盘 ${job.planned_quantity} 套` : '等待清板'}</span></div><p className="mt-1 text-xs text-slate-400">{job.assigned_printer_name || job.virtual_printer_name || '未分配打印机'} · {job.assigned_printer_model || job.printer_model || '未知型号'}</p></button>)}</div>}{selected && action === 'quality' && <div className="rounded-2xl border border-white/10 bg-[#192126] p-4"><label className="text-sm text-slate-300">合格数量<input type="number" min={0} max={selected.planned_quantity} value={good} onChange={event => setGood(Number(event.target.value))} className="mt-2 w-full rounded-xl border border-white/10 bg-[#10171b] px-3 py-3 text-white" /></label></div>}{selected && <button type="button" disabled={mutation.isPending || (action === 'quality' && (good < 0 || good > selected.planned_quantity))} onClick={() => mutation.mutate()} className="w-full rounded-2xl bg-emerald-500 px-4 py-3.5 font-semibold text-slate-950 disabled:opacity-50">{mutation.isPending ? '提交中…' : action === 'quality' ? '确认质检结果' : '确认已清理料盘'}</button>}{mutation.error && <p className="text-sm text-rose-300">{errorText(mutation.error)}</p>}</div>;
}

export function MobileAppPage() {
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [action, setAction] = React.useState<Action | null>(null);
  const [scannerOpen, setScannerOpen] = React.useState(false);
  const [scanCode, setScanCode] = React.useState('');
  const [printer, setPrinter] = React.useState<PrinterConsumableTarget | null>(null);
  const [material, setMaterial] = React.useState('');
  const [colorHex, setColorHex] = React.useState('');
  const [colorName, setColorName] = React.useState('');
  const [message, setMessage] = React.useState('');
  const targets = useQuery({ queryKey: ['mobile-consumable-targets'], queryFn: productionApi.listConsumableTargets, enabled: action === 'change' });
  const units = useQuery({ queryKey: ['mobile-consumable-units'], queryFn: () => productionApi.listConsumableUnits(), enabled: action === 'change' || action === 'receive' || action === 'deplete' || action === 'scrap' });
  const jobs = useQuery({ queryKey: ['mobile-plate-jobs'], queryFn: productionApi.listPlateJobs, enabled: action === 'quality' || action === 'cleanup' });
  const unitMutation = useMutation({ mutationFn: (input: { unit_code: string; action: 'receive' | 'deplete' | 'scrap' }) => productionApi.scanConsumableUnit({ operation_id: `mobile-${input.action}-${Date.now()}`, ...input }), onSuccess: result => { setMessage(`${result.unit_code} 已${result.status === 'in_stock' ? '入库' : result.status === 'depleted' ? '标记用完' : '标记报废'}。`); queryClient.invalidateQueries({ queryKey: ['mobile-consumable-units'] }); setScanCode(''); } });
  const bindingMutation = useMutation({ mutationFn: () => productionApi.scanConsumable({ operation_id: `mobile-bind-${Date.now()}`, scan_code: scanCode, material: material || null, color_hex: colorHex || null, color_name: colorName || null, ...(printer?.kind === 'printer' ? { printer_id: printer.id } : { virtual_printer_id: printer!.id }) }), onSuccess: () => { setMessage('耗材已绑定到打印机，旧耗材已自动替换。'); queryClient.invalidateQueries({ queryKey: ['mobile-consumable-targets'] }); setScanCode(''); } });
  const reset = () => { setAction(null); setScannerOpen(false); setScanCode(''); setPrinter(null); setMaterial(''); setColorHex(''); setColorName(''); setMessage(''); };
  const handleDecoded = React.useCallback((raw: string) => {
    const parsed = parseQr(raw);
    setScannerOpen(false);
    if (action === 'change' && !printer) {
      if (!parsed.targetKey) { setMessage('这不是打印机二维码，请先扫描打印机上的二维码。'); return; }
      const found = targets.data?.find(item => `${item.kind}:${item.id}` === parsed.targetKey) || null;
      setPrinter(found); setMessage(found ? `已锁定打印机：${found.name}，请继续扫描耗材卷。` : '打印机二维码已读取，但服务器找不到该设备。');
      return;
    }
    setScanCode(parsed.code); if (parsed.material) setMaterial(parsed.material); if (parsed.colorHex) setColorHex(parsed.colorHex.startsWith('#') ? parsed.colorHex : `#${parsed.colorHex}`); if (parsed.colorName) setColorName(parsed.colorName); setMessage('二维码识别成功，请检查信息后提交。');
  }, [action, printer, targets.data]);
  if (!getMobileServerUrl()) return <ServerSetup onSaved={() => window.location.reload()} />;
  if (!action) return <div className="min-h-screen bg-[#10171b] px-5 pb-8 text-white"><header className="mx-auto flex max-w-lg items-center justify-between py-6"><div><p className="text-sm text-emerald-400">Bambuddy Mobile</p><h1 className="mt-1 text-2xl font-bold">今天要做什么？</h1></div><button type="button" aria-label="设置服务器" onClick={() => setMobileServerUrl(null)} className="rounded-2xl border border-white/10 p-3 text-slate-300"><Settings size={20} /></button></header><main className="mx-auto max-w-lg"><div className="mb-5 rounded-3xl border border-emerald-400/20 bg-gradient-to-br from-emerald-500/15 to-cyan-500/5 p-5"><div className="flex items-center gap-3"><div className="rounded-2xl bg-emerald-400/20 p-3 text-emerald-300"><Factory size={24} /></div><div><p className="font-semibold">手机操作中心</p><p className="mt-1 text-sm text-slate-400">扫码后按步骤完成，不需要打开桌面菜单。</p></div></div></div><div className="grid grid-cols-2 gap-3">{(Object.keys(actionMeta) as Action[]).map(key => { const item = actionMeta[key]; const Icon = item.icon; return <button type="button" key={key} onClick={() => setAction(key)} className="rounded-3xl border border-white/10 bg-[#192126] p-4 text-left shadow-lg transition hover:-translate-y-0.5 hover:border-white/30"><span className={`inline-flex rounded-2xl bg-gradient-to-br ${item.color} p-3 text-white`}><Icon size={24} /></span><p className="mt-4 font-semibold">{item.title}</p><p className="mt-1 text-xs leading-5 text-slate-400">{item.description}</p><ChevronRight size={16} className="mt-3 text-slate-500" /></button>; })}</div><button type="button" onClick={logout} className="mt-6 flex w-full items-center justify-center gap-2 rounded-2xl border border-white/10 px-4 py-3 text-sm text-slate-400"><CircleHelp size={16} />退出当前账号</button></main></div>;
  const meta = actionMeta[action];
  if ((action === 'quality' || action === 'cleanup') && jobs.data) return <div className="min-h-screen bg-[#10171b] px-5 py-6 text-white"><main className="mx-auto max-w-lg"><JobPicker action={action} jobs={(jobs.data || []).filter(job => (action === 'quality' ? job.workflow_status === 'awaiting_quality' : job.workflow_status === 'waiting_cleanup'))} onDone={() => { setMessage(action === 'quality' ? '质检结果已登记。' : '清理料盘已确认，打印机已释放。'); setAction(null); }} onBack={reset} /></main></div>;
  const isUnitAction = action === 'receive' || action === 'deplete' || action === 'scrap';
  return <div className="min-h-screen bg-[#10171b] px-5 py-6 text-white"><main className="mx-auto max-w-lg"><div className="flex items-center justify-between"><button type="button" onClick={reset} className="flex items-center gap-1 text-sm text-slate-400"><ArrowLeft size={18} />返回首页</button><span className="text-xs text-slate-500">第 1 步 / {action === 'change' ? 3 : 2}</span></div><div className="mt-6 flex items-center gap-3"><span className={`rounded-2xl bg-gradient-to-br ${meta.color} p-3`}><meta.icon size={26} /></span><div><h1 className="text-2xl font-bold">{meta.title}</h1><p className="mt-1 text-sm text-slate-400">{meta.description}</p></div></div><div className="mt-6 space-y-3 rounded-3xl border border-white/10 bg-[#192126] p-5">{action === 'change' && <div className="rounded-2xl bg-[#10171b] p-4"><p className="text-xs text-slate-500">打印机</p><p className="mt-1 font-semibold text-white">{printer?.name || '尚未扫描'}</p><p className="mt-1 text-xs text-slate-400">{printer ? `${printer.model || '未知型号'} · 已锁定` : '点击下方按钮扫描打印机二维码'}</p></div>}{isUnitAction && <div className="rounded-2xl bg-[#10171b] p-4"><p className="text-xs text-slate-500">耗材二维码</p><p className="mt-1 break-all font-mono text-sm text-white">{scanCode || '尚未扫描'}</p>{scanCode && units.data?.find(unit => unit.unit_code === scanCode) && <p className="mt-2 text-sm text-emerald-300">已找到库存记录</p>}</div>}{action === 'change' && scanCode && <div className="grid grid-cols-2 gap-3"><label className="text-xs text-slate-400">材料<input value={material} onChange={event => setMaterial(event.target.value)} className="mt-1 w-full rounded-xl border border-white/10 bg-[#10171b] px-3 py-2 text-white" /></label><label className="text-xs text-slate-400">颜色<input value={colorName} onChange={event => setColorName(event.target.value)} className="mt-1 w-full rounded-xl border border-white/10 bg-[#10171b] px-3 py-2 text-white" /></label></div>}<button type="button" onClick={() => setScannerOpen(true)} className="flex w-full items-center justify-center gap-2 rounded-2xl bg-emerald-500 px-4 py-3.5 font-semibold text-slate-950"><QrCode size={20} />{action === 'change' && !printer ? '扫描打印机二维码' : '打开摄像头扫码'}</button>{isUnitAction && <input value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="也可以手动输入二维码内容" className="w-full rounded-2xl border border-white/10 bg-[#10171b] px-4 py-3 text-white placeholder:text-slate-600" />}{action === 'change' && printer && scanCode && <button type="button" disabled={bindingMutation.isPending} onClick={() => bindingMutation.mutate()} className="w-full rounded-2xl bg-blue-500 px-4 py-3.5 font-semibold text-white disabled:opacity-50">{bindingMutation.isPending ? '登记中…' : '确认绑定耗材'}</button>}{isUnitAction && scanCode && <button type="button" disabled={unitMutation.isPending} onClick={() => unitMutation.mutate({ unit_code: scanCode.trim(), action })} className="w-full rounded-2xl bg-emerald-500 px-4 py-3.5 font-semibold text-slate-950 disabled:opacity-50">{unitMutation.isPending ? '提交中…' : `确认${meta.title}`}</button>}{message && <p className="flex items-center gap-2 rounded-2xl bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300"><CheckCircle2 size={18} />{message}</p>}{(unitMutation.error || bindingMutation.error) && <p className="rounded-2xl bg-rose-400/10 px-4 py-3 text-sm text-rose-300">{errorText(unitMutation.error || bindingMutation.error)}</p>}</div><p className="mt-4 text-center text-xs text-slate-500">扫码只登记到当前 Bambuddy 服务器，不会在手机本地保存库存数据。</p></main>{scannerOpen && <MobileScanner onDecoded={handleDecoded} onClose={() => setScannerOpen(false)} />}</div>;
}
