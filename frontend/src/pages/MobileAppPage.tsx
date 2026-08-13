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
import { parseMobileConnectQrPayload } from '../utils/mobileConnectQr';

type Action = 'receive' | 'change' | 'deplete' | 'scrap' | 'quality' | 'cleanup' | 'maintenance';
type ParsedQr = { code: string; targetKey?: string; serverUrl?: string; material?: string; colorHex?: string; colorName?: string };

const actionMeta: Record<Action, { title: string; description: string; icon: typeof Box; color: string; surface: string; border: string; button: string }> = {
  receive: { title: '耗材入库', description: '扫描卷料二维码，登记到库存', icon: PackageCheck, color: 'from-emerald-500 to-teal-500', surface: 'bg-emerald-500/12', border: 'border-emerald-400/35 hover:border-emerald-300/70', button: 'bg-emerald-500 hover:bg-emerald-400' },
  change: { title: '打印机换料', description: '先扫打印机，再扫耗材卷', icon: Wrench, color: 'from-blue-500 to-cyan-500', surface: 'bg-blue-500/12', border: 'border-blue-400/35 hover:border-blue-300/70', button: 'bg-blue-500 hover:bg-blue-400' },
  deplete: { title: '耗材用完', description: '扫描二维码标记为已用完', icon: PackageMinus, color: 'from-amber-500 to-orange-500', surface: 'bg-amber-500/12', border: 'border-amber-400/35 hover:border-amber-300/70', button: 'bg-amber-500 hover:bg-amber-400' },
  scrap: { title: '耗材报废', description: '扫描二维码记录报废', icon: Trash2, color: 'from-rose-500 to-red-500', surface: 'bg-rose-500/12', border: 'border-rose-400/35 hover:border-rose-300/70', button: 'bg-rose-500 hover:bg-rose-400' },
  quality: { title: '打印质检', description: '先扫对应打印机，再填写本盘结果', icon: ClipboardCheck, color: 'from-violet-500 to-purple-500', surface: 'bg-violet-500/12', border: 'border-violet-400/35 hover:border-violet-300/70', button: 'bg-violet-500 hover:bg-violet-400' },
  cleanup: { title: '清理料盘', description: '扫码或点击需要清理的打印机', icon: Gauge, color: 'from-indigo-500 to-blue-500', surface: 'bg-indigo-500/12', border: 'border-indigo-400/35 hover:border-indigo-300/70', button: 'bg-indigo-500 hover:bg-indigo-400' },
  maintenance: { title: '打印机维修', description: '扫描打印机进入或结束维修', icon: Wrench, color: 'from-orange-500 to-rose-500', surface: 'bg-orange-500/12', border: 'border-orange-400/35 hover:border-orange-300/70', button: 'bg-orange-500 hover:bg-orange-400' },
};

function parseQr(raw: string): ParsedQr {
  const value = raw.trim();
  try {
    const url = new URL(value);
    const targetKey = url.searchParams.get('printer') || undefined;
    const serverUrl = url.searchParams.get('server')
      || (url.protocol === 'http:' || url.protocol === 'https:' ? url.origin : undefined);
    const nested = url.searchParams.get('scan');
    if (nested) return { ...parseQr(nested), ...(targetKey ? { targetKey } : {}), ...(serverUrl ? { serverUrl } : {}) };
    if (url.protocol === 'bambuddy:') {
      return {
        code: url.searchParams.get('code') || value,
        targetKey,
        material: url.searchParams.get('material') || undefined,
        colorHex: url.searchParams.get('color') || undefined,
        colorName: url.searchParams.get('name') || undefined,
      };
    }
    if (targetKey) return { code: '', targetKey, serverUrl };
  } catch {
    // A plain CU-... value is the normal label format.
  }
  return { code: value };
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

function MobileScanner({ prompt, onDecoded, onClose }: { prompt: string; onDecoded: (value: string) => void; onClose: () => void }) {
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
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-2 text-white"><ScanLine size={20} className="text-emerald-400" /><span className="font-semibold">{prompt}</span></div>
        <button type="button" aria-label="关闭扫码" onClick={onClose} className="rounded-full p-2 text-slate-300 hover:bg-white/10"><X size={20} /></button>
      </div>
      <div className="relative mx-5 overflow-hidden rounded-2xl bg-black">
        <video ref={videoRef} muted playsInline className="aspect-square w-full object-cover" />
        <div className="pointer-events-none absolute inset-8 rounded-2xl border-2 border-emerald-400/80" />
        <div className="pointer-events-none absolute inset-x-12 top-1/2 h-0.5 bg-emerald-400/80" />
      </div>
      <p className="px-5 py-4 text-center text-sm text-slate-400">请将{prompt.replace(/^扫描/, '')}放入取景框，识别成功后自动进入下一步。</p>
      {error && <p className="px-5 pb-4 text-center text-sm text-rose-300">{error}</p>}
    </div>
  </div>;
}

function ServerSetup({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = React.useState(getMobileServerUrl());
  const [error, setError] = React.useState('');
  const [scannerOpen, setScannerOpen] = React.useState(false);
  const save = () => {
    const normalized = normalizeServerUrl(value);
    if (!/^https?:\/\//i.test(normalized)) { setError('请输入完整地址，例如 https://192.168.1.20:8019'); return; }
    setMobileServerUrl(normalized);
    onSaved();
  };
  const handleDecoded = (raw: string) => {
    const server = parseMobileConnectQrPayload(raw);
    setScannerOpen(false);
    if (!server) { setError('二维码中没有有效的 Bambuddy 服务地址'); return; }
    setValue(server);
    setError('已读取电脑连接地址，请点击连接服务器');
  };
  return <div className="flex min-h-screen items-center justify-center bg-[#10171b] p-6 text-white">
    <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#192126] p-7 shadow-2xl">
      <div className="mb-6 flex items-center gap-3"><div className="rounded-2xl bg-emerald-500/15 p-3 text-emerald-400"><Factory size={28} /></div><div><h1 className="text-2xl font-bold">连接 Bambuddy</h1><p className="mt-1 text-sm text-slate-400">扫描电脑设置中的二维码即可连接</p></div></div>
      <label className="text-sm text-slate-300">服务器 HTTPS 地址<input autoFocus value={value} onChange={event => setValue(event.target.value)} placeholder="https://192.168.1.20:8019" className="mt-2 w-full rounded-2xl border border-white/10 bg-[#10171b] px-4 py-3 text-white outline-none focus:border-emerald-400" /></label>
      <p className="mt-3 text-xs leading-5 text-slate-500">电脑和手机需要在同一局域网。使用 HTTPS 才能打开摄像头；自签名证书首次需要在手机浏览器中信任。</p>
      {error && <p className="mt-3 text-sm text-amber-300">{error}</p>}
      <div className="mt-6 grid grid-cols-2 gap-3"><button type="button" onClick={() => setScannerOpen(true)} className="flex items-center justify-center gap-2 rounded-2xl border border-emerald-400/40 px-4 py-3.5 font-semibold text-emerald-300 hover:bg-emerald-400/10"><ScanLine size={19} />扫描电脑二维码</button><button type="button" onClick={save} className="rounded-2xl bg-emerald-500 px-4 py-3.5 font-semibold text-slate-950 hover:bg-emerald-400">连接服务器</button></div>
    </div>
    {scannerOpen && <MobileScanner prompt="扫描电脑连接二维码" onDecoded={handleDecoded} onClose={() => setScannerOpen(false)} />}
  </div>;
}

function JobPicker({ action, printerName, jobs, onDone, onBack }: { action: 'quality'; printerName: string; jobs: PlateJob[]; onDone: () => void; onBack: () => void }) {
  const [selectedId, setSelectedId] = React.useState<number | null>(null);
  const [good, setGood] = React.useState(0);
  const queryClient = useQueryClient();
  const selected = jobs.find(job => job.id === selectedId);
  React.useEffect(() => { if (selected) setGood(selected.planned_quantity); }, [selected]);
  const mutation = useMutation({
    mutationFn: () => productionApi.advanceWorkflow(selected!.id, action, { good_quantity: good }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['mobile-plate-jobs'] }); onDone(); },
  });

  return <div className="space-y-4">
    <div className="flex items-center justify-between"><button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-slate-400"><ArrowLeft size={16} />重新扫描打印机</button><span className="text-sm text-slate-400">打印质检</span></div>
    <div className="rounded-2xl border border-violet-400/30 bg-violet-400/10 p-4"><p className="text-xs text-violet-200">已扫描打印机</p><p className="mt-1 font-semibold text-white">{printerName}</p><p className="mt-1 text-xs text-violet-100/70">只显示这台打印机对应的待质检任务</p></div>
    {jobs.length === 0 ? <div className="rounded-2xl border border-white/10 bg-[#192126] p-6 text-center text-slate-400">这台打印机当前没有待质检任务。</div> : <div className="space-y-2">{jobs.map(job => <button type="button" key={job.id} onClick={() => setSelectedId(job.id)} className={`w-full rounded-2xl border p-4 text-left transition ${selectedId === job.id ? 'border-emerald-400 bg-emerald-400/10' : 'border-white/10 bg-[#192126] hover:border-white/30'}`}><div className="flex items-center justify-between text-white"><span>打印任务 #{job.id}</span><span className="text-sm text-emerald-300">本盘 {job.planned_quantity} 套</span></div><p className="mt-1 text-xs text-slate-400">{job.assigned_printer_name || '未分配打印机'} · {job.assigned_printer_model || job.printer_model || '未知型号'}</p></button>)}</div>}
    {selected && <div className="rounded-2xl border border-white/10 bg-[#192126] p-4"><label className="text-sm text-slate-300">合格数量<input type="number" min={0} max={selected.planned_quantity} value={good} onChange={event => setGood(Number(event.target.value))} className="mt-2 w-full rounded-xl border border-white/10 bg-[#10171b] px-3 py-3 text-white" /></label><p className="mt-2 text-xs text-slate-500">少于本盘数量的部分会记录为不合格，不计入成功数量。</p></div>}
    {selected && <button type="button" disabled={mutation.isPending || good < 0 || good > selected.planned_quantity} onClick={() => mutation.mutate()} className="w-full rounded-2xl bg-violet-500 px-4 py-3.5 font-semibold text-white shadow-lg shadow-violet-500/20 hover:bg-violet-400 disabled:opacity-50">{mutation.isPending ? '提交中…' : '确认质检结果'}</button>}
    {mutation.error && <p className="text-sm text-rose-300">{errorText(mutation.error)}</p>}
  </div>;
}

type CleanupPanelProps = {
  printers: PrinterConsumableTarget[];
  cleanupJobs: PlateJob[];
  selectedPrinter: PrinterConsumableTarget | null;
  onSelectPrinter: (printer: PrinterConsumableTarget | null) => void;
  onScan: () => void;
  onBack: () => void;
  onInvalidate: () => void;
};

function CleanupPanel({ printers, cleanupJobs, selectedPrinter, onSelectPrinter, onScan, onBack, onInvalidate }: CleanupPanelProps) {
  const cleanupForPrinter = (printerId: number) => cleanupJobs.filter(job => job.assigned_printer_id === printerId);
  const queryClient = useQueryClient();
  const clearOne = useMutation({
    mutationFn: async (printer: PrinterConsumableTarget) => {
      const jobs = cleanupForPrinter(printer.id);
      if (jobs.length) {
        for (const job of jobs) await productionApi.advanceWorkflow(job.id, 'cleanup');
      } else {
        await productionApi.clearPlate(printer.id);
      }
      return printer;
    },
    onSuccess: () => { onSelectPrinter(null); onInvalidate(); queryClient.invalidateQueries({ queryKey: ['mobile-plate-jobs'] }); },
    onSettled: () => { queryClient.invalidateQueries({ queryKey: ['mobile-consumable-targets'] }); },
  });
  const clearAll = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(printers.map(async printer => {
        const jobs = cleanupForPrinter(printer.id);
        if (jobs.length) {
          for (const job of jobs) await productionApi.advanceWorkflow(job.id, 'cleanup');
        } else {
          await productionApi.clearPlate(printer.id);
        }
        return printer.name;
      }));
      const failed = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failed.length) throw new Error(`已完成 ${printers.length - failed.length} 台，${failed.length} 台失败：${errorText(failed[0].reason)}`);
      return printers.length;
    },
    onSuccess: () => { onSelectPrinter(null); onInvalidate(); queryClient.invalidateQueries({ queryKey: ['mobile-plate-jobs'] }); },
    onSettled: () => { queryClient.invalidateQueries({ queryKey: ['mobile-consumable-targets'] }); },
  });
  const busy = clearOne.isPending || clearAll.isPending;
  const selectedJobs = selectedPrinter ? cleanupForPrinter(selectedPrinter.id) : [];

  return <div className="space-y-4">
    <div className="flex items-center justify-between"><button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-slate-400"><ArrowLeft size={16} />返回首页</button><span className="text-sm text-slate-400">清理料盘</span></div>
    <div className="rounded-2xl border border-indigo-400/30 bg-indigo-400/10 p-4"><p className="text-sm font-semibold text-white">需要清理料盘的打印机</p><p className="mt-1 text-xs text-indigo-100/75">可以点击列表选择，也可以扫描打印机二维码快速定位。</p></div>
    <button type="button" onClick={onScan} className="flex w-full items-center justify-center gap-2 rounded-2xl bg-indigo-500 px-4 py-3.5 font-semibold text-white shadow-lg shadow-indigo-500/20 hover:bg-indigo-400"><QrCode size={20} />扫描打印机二维码</button>
    {printers.length === 0 ? <div className="rounded-2xl border border-white/10 bg-[#192126] p-6 text-center text-slate-400">当前没有需要清理料盘的打印机。</div> : <div className="space-y-2">{printers.map(printer => { const jobs = cleanupForPrinter(printer.id); return <button type="button" key={`${printer.kind}:${printer.id}`} onClick={() => onSelectPrinter(printer)} className={`w-full rounded-2xl border p-4 text-left transition ${selectedPrinter?.id === printer.id ? 'border-indigo-400 bg-indigo-400/10' : 'border-white/10 bg-[#192126] hover:border-white/30'}`}><div className="flex items-center justify-between"><span className="font-semibold text-white">{printer.name}</span><span className="text-xs text-amber-300">待清理</span></div><p className="mt-1 text-xs text-slate-400">{printer.model || '未知型号'}{jobs.length ? ` · ${jobs.length} 个生产任务` : ' · 打印机状态待确认'}</p></button>; })}</div>}
    {printers.length > 0 && <button type="button" disabled={busy} onClick={() => clearAll.mutate()} className="w-full rounded-2xl border border-amber-400/60 bg-amber-400/10 px-4 py-3.5 font-semibold text-amber-200 disabled:opacity-50">{clearAll.isPending ? '正在全部清理…' : `全部清理（${printers.length} 台）`}</button>}
    {selectedPrinter && <div className="rounded-2xl border border-indigo-400/30 bg-indigo-500/10 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs text-indigo-200/70">当前选择</p><p className="mt-1 font-semibold text-white">{selectedPrinter.name}</p><p className="mt-1 text-xs text-slate-300">{selectedPrinter.model || '未知型号'} · {selectedJobs.length ? `关联 ${selectedJobs.length} 个待清理任务` : '直接清除打印机待确认状态'}</p></div><button type="button" onClick={onScan} className="rounded-xl border border-indigo-300/30 px-3 py-2 text-xs text-indigo-100 hover:bg-indigo-400/15">重新扫码</button></div><button type="button" disabled={busy} onClick={() => clearOne.mutate(selectedPrinter)} className="mt-4 w-full rounded-2xl bg-indigo-500 px-4 py-3.5 font-semibold text-white shadow-lg shadow-indigo-500/20 hover:bg-indigo-400 disabled:opacity-50">{clearOne.isPending ? '提交中…' : `清理 ${selectedPrinter.name} 料盘`}</button></div>}
    {(clearOne.error || clearAll.error) && <p className="rounded-2xl bg-rose-400/10 px-4 py-3 text-sm text-rose-300">{errorText(clearOne.error || clearAll.error)}</p>}
  </div>;
}

type MaintenancePanelProps = {
  selectedPrinter: PrinterConsumableTarget | null;
  onSelectPrinter: (printer: PrinterConsumableTarget | null) => void;
  onScan: () => void;
  onBack: () => void;
  onInvalidate: () => void;
};

function MaintenancePanel({ selectedPrinter, onSelectPrinter, onScan, onBack, onInvalidate }: MaintenancePanelProps) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (maintenance: boolean) => productionApi.setPrinterMaintenance(selectedPrinter!.id, maintenance),
    onSuccess: result => {
      onSelectPrinter({ ...selectedPrinter!, is_active: result.is_active });
      onInvalidate();
      queryClient.invalidateQueries({ queryKey: ['mobile-consumable-targets'] });
    },
  });

  return <div className="space-y-4">
    <div className="flex items-center justify-between"><button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-slate-400"><ArrowLeft size={16} />返回首页</button><span className="text-sm text-slate-400">打印机维修</span></div>
    <div className="rounded-2xl border border-orange-400/30 bg-orange-400/10 p-4"><p className="text-sm font-semibold text-white">维修状态</p><p className="mt-1 text-xs text-orange-100/80">扫描对应打印机后，可以暂停或恢复它的接单资格。维修中的打印机不会接收新的打印任务。</p></div>
    <button type="button" onClick={onScan} className="flex w-full items-center justify-center gap-2 rounded-2xl bg-orange-500 px-4 py-3.5 font-semibold text-white shadow-lg shadow-orange-500/20 hover:bg-orange-400"><QrCode size={20} />扫描打印机二维码</button>
    {!selectedPrinter ? <div className="rounded-2xl border border-orange-400/30 bg-orange-500/10 p-6 text-center text-orange-100/80">尚未选择打印机，请扫描需要维修的机器。</div> : <div className="rounded-2xl border border-orange-400/30 bg-orange-500/10 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs text-orange-100/70">当前打印机</p><p className="mt-1 font-semibold text-white">{selectedPrinter.name}</p><p className="mt-1 text-xs text-orange-50/80">{selectedPrinter.model || '未知型号'} · {selectedPrinter.is_active === false ? '当前处于维修中' : '当前可以接单'}</p></div><button type="button" onClick={onScan} className="rounded-xl border border-orange-200/30 px-3 py-2 text-xs text-orange-50 hover:bg-orange-400/15">重新扫码</button></div><button type="button" disabled={mutation.isPending} onClick={() => mutation.mutate(selectedPrinter.is_active !== false)} className={`mt-4 w-full rounded-2xl px-4 py-3.5 font-semibold text-white shadow-lg disabled:opacity-50 ${selectedPrinter.is_active === false ? 'bg-emerald-500 shadow-emerald-500/20 hover:bg-emerald-400' : 'bg-orange-500 shadow-orange-500/20 hover:bg-orange-400'}`}>{mutation.isPending ? '提交中…' : selectedPrinter.is_active === false ? '维修完成，恢复接单' : '确认进入维修'}</button>{mutation.error && <p className="mt-3 rounded-2xl bg-rose-400/10 px-4 py-3 text-sm text-rose-300">{errorText(mutation.error)}</p>}<p className="mt-3 text-xs leading-5 text-orange-50/65">进入维修只会禁止新的任务分配并断开后台连接，不会自动停止正在打印的任务；如机器正在打印，请先停止当前打印。</p></div>}
  </div>;
}

export function MobileAppPage() {
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [action, setAction] = React.useState<Action | null>(null);
  const [scannerOpen, setScannerOpen] = React.useState(false);
  const [scanCode, setScanCode] = React.useState('');
  const [printer, setPrinter] = React.useState<PrinterConsumableTarget | null>(null);
  const [pendingPrinterKey, setPendingPrinterKey] = React.useState<string | null>(null);
  const [material, setMaterial] = React.useState('');
  const [colorHex, setColorHex] = React.useState('');
  const [colorName, setColorName] = React.useState('');
  const [message, setMessage] = React.useState('');
  const [activeServerUrl, setActiveServerUrl] = React.useState(() => getMobileServerUrl());

  const printerScanAction = action === 'quality' || action === 'cleanup' || action === 'maintenance' || (action === 'change' && !printer);
  const targets = useQuery({
    queryKey: ['mobile-consumable-targets', activeServerUrl],
    queryFn: productionApi.listConsumableTargets,
    enabled: action === 'change' || action === 'quality' || action === 'cleanup' || action === 'maintenance',
    retry: false,
  });
  const units = useQuery({ queryKey: ['mobile-consumable-units'], queryFn: () => productionApi.listConsumableUnits(), enabled: action === 'change' || action === 'receive' || action === 'deplete' || action === 'scrap' });
  const jobs = useQuery({ queryKey: ['mobile-plate-jobs'], queryFn: productionApi.listPlateJobs, enabled: action === 'quality' || action === 'cleanup' });

  const unitMutation = useMutation({
    mutationFn: (input: { unit_code: string; action: 'receive' | 'deplete' | 'scrap' }) => productionApi.scanConsumableUnit({ operation_id: `mobile-${input.action}-${Date.now()}`, ...input }),
    onSuccess: result => { setMessage(`${result.unit_code} 已${result.status === 'in_stock' ? '入库' : result.status === 'depleted' ? '标记用完' : '标记报废'}。`); queryClient.invalidateQueries({ queryKey: ['mobile-consumable-units'] }); setScanCode(''); },
  });
  const bindingMutation = useMutation({
    mutationFn: () => productionApi.scanConsumable({ operation_id: `mobile-bind-${Date.now()}`, scan_code: scanCode, material: material || null, color_hex: colorHex || null, color_name: colorName || null, ...(printer?.kind === 'printer' ? { printer_id: printer.id } : { virtual_printer_id: printer!.id }) }),
    onSuccess: () => { setMessage('耗材已绑定到打印机，旧耗材已自动替换。'); queryClient.invalidateQueries({ queryKey: ['mobile-consumable-targets'] }); setScanCode(''); },
  });

  const reset = React.useCallback(() => { setAction(null); setScannerOpen(false); setScanCode(''); setPrinter(null); setPendingPrinterKey(null); setMaterial(''); setColorHex(''); setColorName(''); setMessage(''); }, []);
  const startAction = (nextAction: Action) => { setAction(nextAction); setScannerOpen(true); setScanCode(''); setPrinter(null); setPendingPrinterKey(null); setMaterial(''); setColorHex(''); setColorName(''); setMessage(''); };
  const cleanupJobs = (jobs.data || []).filter(job => job.workflow_status === 'waiting_cleanup' && job.assigned_printer_id != null);
  const cleanupPrinters = (targets.data || []).filter(target => target.kind === 'printer' && (target.awaiting_plate_clear || cleanupJobs.some(job => job.assigned_printer_id === target.id)));
  const qualityJobs = printer ? (jobs.data || []).filter(job => job.workflow_status === 'awaiting_quality' && job.assigned_printer_id === printer.id) : [];
  const targetData = targets.data;
  const refetchTargets = targets.refetch;

  React.useEffect(() => {
    if (!pendingPrinterKey || !['change', 'quality', 'cleanup', 'maintenance'].includes(action || '')) return;
    if (targets.isError || !targets.data) return;
    const found = targets.data.find(item => `${item.kind}:${item.id}` === pendingPrinterKey) || null;
    setPendingPrinterKey(null);
    if (!found) { setPrinter(null); setMessage('服务器当前未找到该打印机，请确认二维码对应服务器和设备列表。'); return; }
    if (action !== 'change' && found.kind !== 'printer') { setPrinter(null); setMessage('质检、清理料盘和维修必须扫描真实打印机二维码。'); return; }
    setPrinter(found);
    setMessage(action === 'change' ? `已锁定打印机：${found.name}，请继续扫描耗材卷。` : `已定位打印机：${found.name}。`);
    if (action === 'change') setScannerOpen(true);
  }, [action, pendingPrinterKey, targets.data, targets.isError]);

  const handleDecoded = React.useCallback((raw: string) => {
    const parsed = parseQr(raw);
    setScannerOpen(false);
    if (printerScanAction) {
      if (!parsed.targetKey) { setMessage('这不是打印机二维码，请扫描打印机上的二维码。'); return; }
      const scannedServerUrl = parsed.serverUrl ? normalizeServerUrl(parsed.serverUrl) : '';
      if (scannedServerUrl && scannedServerUrl !== activeServerUrl) {
        setMobileServerUrl(scannedServerUrl);
        setActiveServerUrl(scannedServerUrl);
        setPrinter(null);
        setPendingPrinterKey(parsed.targetKey);
        setMessage('已读取打印机二维码，正在切换到对应服务器并刷新设备列表…');
        return;
      }
      const found = targetData?.find(item => `${item.kind}:${item.id}` === parsed.targetKey) || null;
      if (!found) {
        if (!targetData) { setPendingPrinterKey(parsed.targetKey); setMessage('已读取打印机二维码，正在从服务器刷新设备列表…'); void refetchTargets(); }
        else setMessage('服务器当前未找到该打印机，请确认 App 连接的是生成二维码的服务器。');
        return;
      }
      if ((action === 'quality' || action === 'cleanup' || action === 'maintenance') && found.kind !== 'printer') { setMessage('质检、清理料盘和维修必须扫描真实打印机二维码。'); return; }
      setPrinter(found);
      setMessage(action === 'change' ? `已锁定打印机：${found.name}，请继续扫描耗材卷。` : `已定位打印机：${found.name}。`);
      if (action === 'change') setScannerOpen(true);
      return;
    }
    if (!parsed.code) { setMessage('没有读取到耗材二维码内容，请重新扫描。'); return; }
    setScanCode(parsed.code);
    if (parsed.material) setMaterial(parsed.material);
    if (parsed.colorHex) setColorHex(parsed.colorHex.startsWith('#') ? parsed.colorHex : `#${parsed.colorHex}`);
    if (parsed.colorName) setColorName(parsed.colorName);
    setMessage('二维码识别成功，请检查信息后提交。');
  }, [action, activeServerUrl, printerScanAction, refetchTargets, targetData]);

  if (!getMobileServerUrl()) return <ServerSetup onSaved={() => window.location.reload()} />;
  if (!action) return <div className="min-h-screen bg-[#10171b] px-5 pb-8 text-white"><header className="mx-auto flex max-w-lg items-center justify-between py-6"><div><p className="text-sm text-emerald-400">Bambuddy Mobile</p><h1 className="mt-1 text-2xl font-bold">今天要做什么？</h1></div><button type="button" aria-label="设置服务器" onClick={() => setMobileServerUrl(null)} className="rounded-2xl border border-white/10 p-3 text-slate-300 hover:border-emerald-400/50 hover:bg-emerald-400/10"><Settings size={20} /></button></header><main className="mx-auto max-w-lg"><div className="mb-5 rounded-3xl border border-emerald-400/20 bg-gradient-to-br from-emerald-500/15 to-cyan-500/5 p-5"><div className="flex items-center gap-3"><div className="rounded-2xl bg-emerald-400/20 p-3 text-emerald-300"><Factory size={24} /></div><div><p className="font-semibold">手机操作中心</p><p className="mt-1 text-sm text-slate-400">点击任意操作后立即扫码，不再经过中间页面。</p></div></div></div><div className="grid grid-cols-2 gap-3">{(Object.keys(actionMeta) as Action[]).map(key => { const item = actionMeta[key]; const Icon = item.icon; return <button type="button" key={key} onClick={() => startAction(key)} className={`rounded-3xl border p-4 text-left shadow-lg shadow-black/10 transition hover:-translate-y-0.5 hover:shadow-xl ${item.surface} ${item.border}`}><span className={`inline-flex rounded-2xl bg-gradient-to-br ${item.color} p-3 text-white shadow-lg`}><Icon size={24} /></span><p className="mt-4 font-semibold text-white">{item.title}</p><p className="mt-1 text-xs leading-5 text-slate-200/75">{item.description}</p><ChevronRight size={16} className="mt-3 text-slate-300" /></button>; })}</div><button type="button" onClick={logout} className="mt-6 flex w-full items-center justify-center gap-2 rounded-2xl border border-white/10 px-4 py-3 text-sm text-slate-400 hover:border-slate-400/40 hover:bg-white/5"><CircleHelp size={16} />退出当前账号</button></main></div>;

  const meta = actionMeta[action];
  if (action === 'maintenance') return <div className="min-h-screen bg-[#10171b] px-5 py-6 text-white"><main className="mx-auto max-w-lg"><MaintenancePanel selectedPrinter={printer} onSelectPrinter={setPrinter} onScan={() => { setPrinter(null); setScannerOpen(true); }} onBack={reset} onInvalidate={() => setMessage('维修状态已更新。')} /></main>{message && <p className="mx-auto mt-4 flex max-w-lg items-center gap-2 rounded-2xl bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300"><CheckCircle2 size={18} />{message}</p>}{scannerOpen && <MobileScanner prompt="扫描要维修的打印机二维码" onDecoded={handleDecoded} onClose={() => setScannerOpen(false)} />}</div>;
  if (action === 'quality' && printer && jobs.data) return <div className="min-h-screen bg-[#10171b] px-5 py-6 text-white"><main className="mx-auto max-w-lg"><JobPicker action="quality" printerName={printer.name} jobs={qualityJobs} onDone={reset} onBack={() => { setPrinter(null); setMessage('请重新扫描要质检的打印机二维码。'); setScannerOpen(true); }} /></main>{scannerOpen && <MobileScanner prompt="扫描要质检的打印机二维码" onDecoded={handleDecoded} onClose={() => setScannerOpen(false)} />}</div>;
  if (action === 'cleanup') return <div className="min-h-screen bg-[#10171b] px-5 py-6 text-white"><main className="mx-auto max-w-lg"><CleanupPanel printers={cleanupPrinters} cleanupJobs={cleanupJobs} selectedPrinter={printer} onSelectPrinter={setPrinter} onScan={() => { setPrinter(null); setScannerOpen(true); }} onBack={reset} onInvalidate={() => { queryClient.invalidateQueries({ queryKey: ['mobile-consumable-targets'] }); queryClient.invalidateQueries({ queryKey: ['mobile-plate-jobs'] }); setMessage('料盘清理已完成，列表正在刷新。'); }} /></main>{message && <p className="mx-auto mt-4 flex max-w-lg items-center gap-2 rounded-2xl bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300"><CheckCircle2 size={18} />{message}</p>}{scannerOpen && <MobileScanner prompt="扫描需要清理料盘的打印机二维码" onDecoded={handleDecoded} onClose={() => setScannerOpen(false)} />}</div>;

  const isUnitAction = action === 'receive' || action === 'deplete' || action === 'scrap';
  const scannerPrompt = action === 'quality' ? '扫描要质检的打印机二维码' : action === 'change' && !printer ? '扫描打印机二维码' : '扫描耗材二维码';
  return <div className="min-h-screen bg-[#10171b] px-5 py-6 text-white"><main className="mx-auto max-w-lg"><div className="flex items-center justify-between"><button type="button" onClick={reset} className="flex items-center gap-1 text-sm text-slate-400 hover:text-white"><ArrowLeft size={18} />返回首页</button><span className="text-xs text-slate-400">{action === 'quality' ? '打印质检' : action === 'change' ? '第 2 步 / 3' : '请扫码完成操作'}</span></div><div className="mt-6 flex items-center gap-3"><span className={`rounded-2xl bg-gradient-to-br ${meta.color} p-3 shadow-lg`}><meta.icon size={26} /></span><div><h1 className="text-2xl font-bold">{meta.title}</h1><p className="mt-1 text-sm text-slate-300">{meta.description}</p></div></div><div className={`mt-6 space-y-3 rounded-3xl border p-5 shadow-lg ${meta.surface} ${meta.border.split(' ')[0]}`}>{action === 'change' && <div className="rounded-2xl bg-[#10171b]/70 p-4"><p className="text-xs text-slate-400">打印机</p><p className="mt-1 font-semibold text-white">{printer?.name || '尚未扫描'}</p><p className="mt-1 text-xs text-slate-300">{printer ? `${printer.model || '未知型号'} · 已锁定` : '点击入口后已直接打开扫码'}</p></div>}{action === 'quality' && <div className="rounded-2xl bg-[#10171b]/70 p-4"><p className="text-xs text-violet-100/80">质检打印机</p><p className="mt-1 font-semibold text-white">{printer?.name || '尚未扫描'}</p><p className="mt-1 text-xs text-violet-50/70">请扫描真实打印机二维码，系统会筛选对应任务</p></div>}{isUnitAction && <div className="rounded-2xl bg-[#10171b]/70 p-4"><p className="text-xs text-slate-400">耗材二维码</p><p className="mt-1 break-all font-mono text-sm text-white">{scanCode || '尚未扫描'}</p>{scanCode && units.data?.find(unit => unit.unit_code === scanCode) && <p className="mt-2 text-sm text-emerald-300">已找到库存记录</p>}</div>}{action === 'change' && scanCode && <div className="grid grid-cols-2 gap-3"><label className="text-xs text-slate-300">材料<input value={material} onChange={event => setMaterial(event.target.value)} className="mt-1 w-full rounded-xl border border-blue-300/30 bg-[#10171b]/70 px-3 py-2 text-white" /></label><label className="text-xs text-slate-300">颜色<input value={colorName} onChange={event => setColorName(event.target.value)} className="mt-1 w-full rounded-xl border border-blue-300/30 bg-[#10171b]/70 px-3 py-2 text-white" /></label></div>}<button type="button" onClick={() => setScannerOpen(true)} className={`flex w-full items-center justify-center gap-2 rounded-2xl px-4 py-3.5 font-semibold text-white shadow-lg ${meta.button}`}><QrCode size={20} />{action === 'change' && printer ? '扫描耗材二维码' : scannerPrompt}</button>{(action === 'change' || action === 'quality') && pendingPrinterKey && targets.isError && <><p className="rounded-2xl bg-rose-400/10 px-4 py-3 text-sm text-rose-300">无法读取 {activeServerUrl || '当前服务器'} 的设备列表：{errorText(targets.error)}。请确认手机和电脑在同一局域网后重试。</p><button type="button" onClick={() => { setMessage('正在重新连接服务器…'); void targets.refetch(); }} className="w-full rounded-2xl border border-rose-400/50 px-4 py-3 text-sm font-semibold text-rose-200 hover:bg-rose-400/10">重试连接服务器</button></>}{isUnitAction && <input value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="也可以手动输入二维码内容" className="w-full rounded-2xl border border-white/20 bg-[#10171b]/70 px-4 py-3 text-white placeholder:text-slate-500" />}{action === 'change' && printer && scanCode && <button type="button" disabled={bindingMutation.isPending} onClick={() => bindingMutation.mutate()} className={`w-full rounded-2xl px-4 py-3.5 font-semibold text-white shadow-lg disabled:opacity-50 ${meta.button}`}>{bindingMutation.isPending ? '登记中…' : '确认绑定耗材'}</button>}{isUnitAction && scanCode && <button type="button" disabled={unitMutation.isPending} onClick={() => unitMutation.mutate({ unit_code: scanCode.trim(), action })} className={`w-full rounded-2xl px-4 py-3 font-semibold text-white shadow-lg disabled:opacity-50 ${meta.button}`}>{unitMutation.isPending ? '提交中…' : `确认${meta.title}`}</button>}{message && <p className="flex items-center gap-2 rounded-2xl bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200"><CheckCircle2 size={18} />{message}</p>}{(unitMutation.error || bindingMutation.error) && <p className="rounded-2xl bg-rose-400/10 px-4 py-3 text-sm text-rose-300">{errorText(unitMutation.error || bindingMutation.error)}</p>}</div><p className="mt-4 text-center text-xs text-slate-400">扫码只登记到当前 Bambuddy 服务器，不会在手机本地保存库存数据。</p></main>{scannerOpen && <MobileScanner prompt={scannerPrompt} onDecoded={handleDecoded} onClose={() => setScannerOpen(false)} />}</div>;
}
