import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Camera, CheckCircle2, ScanLine, X } from 'lucide-react';
import { productionApi } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';

const inputClass = 'mt-1 w-full bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white';
const operationId = () => 'direct-consumable-' + Date.now() + '-' + Math.random();

export function PrinterConsumablesPage() {
  const queryClient = useQueryClient();
  const targets = useQuery({ queryKey: ['printer-consumable-targets'], queryFn: productionApi.listConsumableTargets });
  const bindings = useQuery({ queryKey: ['printer-consumables'], queryFn: productionApi.listConsumables });
  const [targetKey, setTargetKey] = React.useState('');
  const [scanCode, setScanCode] = React.useState('');
  const [material, setMaterial] = React.useState('PLA');
  const [colorHex, setColorHex] = React.useState('#FF0000');
  const [colorName, setColorName] = React.useState('');
  const [message, setMessage] = React.useState('');
  const [cameraOpen, setCameraOpen] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const deepLinkApplied = React.useRef(false);
  const scan = useMutation({
    mutationFn: productionApi.scanConsumable,
    onSuccess: result => {
      queryClient.invalidateQueries({ queryKey: ['printer-consumables'] });
      queryClient.invalidateQueries({ queryKey: ['printer-consumable-targets'] });
      setMessage(result.replayed ? '重复扫描已安全重放，没有产生重复记录。' : result.replaced_id ? '新耗材已登记，旧耗材已自动替换。' : '耗材已登记并绑定到打印机。');
      setScanCode('');
    },
  });
  const selected = targets.data?.find(item => item.kind + ':' + item.id === targetKey);
  const applyScannedPayload = React.useCallback((rawValue: string) => {
    try {
      const parsed = new URL(rawValue);
      if (parsed.protocol === 'bambuddy:') {
        setScanCode(parsed.searchParams.get('code') || rawValue);
        setMaterial(parsed.searchParams.get('material') || material);
        setColorHex(parsed.searchParams.get('color') || colorHex);
        setColorName(parsed.searchParams.get('name') || colorName);
      } else {
        setScanCode(rawValue);
      }
    } catch {
      setScanCode(rawValue);
    }
    setCameraOpen(false);
    setMessage('二维码已读取，请确认打印机后提交登记。');
  }, [colorHex, colorName, material]);
  React.useEffect(() => {
    if (deepLinkApplied.current) return;
    const encoded = new URLSearchParams(window.location.search).get('scan');
    if (!encoded) return;
    deepLinkApplied.current = true;
    applyScannedPayload(encoded);
  }, [applyScannedPayload]);
  React.useEffect(() => {
    if (!cameraOpen) return;
    let stream: MediaStream | null = null;
    let frame = 0;
    let stopped = false;
    const start = async () => {
      const detectorCtor = (window as unknown as { BarcodeDetector?: new (options?: { formats: string[] }) => { detect: (source: HTMLVideoElement) => Promise<Array<{ rawValue: string }>> } }).BarcodeDetector;
      if (!detectorCtor || !navigator.mediaDevices?.getUserMedia) {
        setMessage('当前浏览器不支持摄像头二维码识别，请使用扫码枪或手动输入。');
        setCameraOpen(false);
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
        if (!videoRef.current) return;
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        const detector = new detectorCtor({ formats: ['qr_code'] });
        const scanFrame = async () => {
          if (stopped || !videoRef.current) return;
          try {
            const codes = await detector.detect(videoRef.current);
            if (codes[0]?.rawValue) {
              applyScannedPayload(codes[0].rawValue);
              return;
            }
          } catch { /* camera frame may not be ready yet */ }
          frame = requestAnimationFrame(scanFrame);
        };
        frame = requestAnimationFrame(scanFrame);
      } catch {
        setMessage('无法打开手机摄像头，请检查浏览器权限或改用手动输入。');
        setCameraOpen(false);
      }
    };
    void start();
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      stream?.getTracks().forEach(track => track.stop());
    };
  }, [applyScannedPayload, cameraOpen]);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || !scanCode.trim()) return;
    scan.mutate({ operation_id: operationId(), scan_code: scanCode.trim(), material: material.trim().toUpperCase(), color_hex: colorHex, color_name: colorName.trim() || null, ...(selected.kind === 'printer' ? { printer_id: selected.id } : { virtual_printer_id: selected.id }) });
  };
  return <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-6">
    <div><h1 className="text-3xl font-bold text-white">直供耗材登记</h1><p className="text-bambu-gray mt-1">扫码新耗材后自动替换该打印机的旧直供耗材；AMS 槽位不会被修改。</p></div>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white flex items-center gap-2"><ScanLine size={20} />模拟扫码测试</h2></CardHeader><CardContent>
      <form onSubmit={submit} className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
        <label className="text-sm text-bambu-gray">打印机<select aria-label="选择打印机" required value={targetKey} onChange={event => setTargetKey(event.target.value)} className={inputClass}><option value="">选择打印机</option>{(targets.data ?? []).map(item => <option key={item.kind + ':' + item.id} value={item.kind + ':' + item.id}>{item.name} · {item.kind === 'virtual_printer' ? '软件测试' : '真实设备'}{item.model ? ' · ' + item.model : ''}</option>)}</select></label>
        <label className="text-sm text-bambu-gray">扫描码<input aria-label="扫描码" required value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="扫码枪输入后回车" className={inputClass} /></label>
        <label className="text-sm text-bambu-gray">材料<input aria-label="材料" required value={material} onChange={event => setMaterial(event.target.value)} className={inputClass} /></label>
        <label className="text-sm text-bambu-gray">颜色<span className="mt-1 flex gap-2"><input aria-label="颜色值" type="color" value={colorHex} onChange={event => setColorHex(event.target.value)} className="h-10 w-14 bg-bambu-dark" /><input aria-label="颜色名称" value={colorName} onChange={event => setColorName(event.target.value)} placeholder="例如 红色" className="flex-1 bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white" /></span></label>
        <div className="md:col-span-2 flex items-end gap-3"><Button type="button" variant="secondary" onClick={() => setCameraOpen(true)}><Camera size={16} />打开摄像头扫码</Button><Button type="submit" disabled={scan.isPending || !selected}><ScanLine size={16} />确认登记</Button>{message && <span className="text-sm text-bambu-green flex items-center gap-1"><CheckCircle2 size={16} />{message}</span>}{scan.error && <span className="text-sm text-red-400">{String(scan.error)}</span>}</div>
      </form>
      <p className="text-xs text-bambu-gray mt-3">当前是软件扫码测试入口。真实扫码器后续只需调用同一个接口，不会自动连接打印机。</p>
    </CardContent></Card>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white">当前直供耗材</h2></CardHeader><CardContent>{(bindings.data ?? []).length === 0 ? <p className="text-bambu-gray">还没有登记直供耗材。</p> : <div className="grid md:grid-cols-2 gap-3">{(bindings.data ?? []).map(binding => <div key={binding.id} className="rounded border border-bambu-gray-dark bg-bambu-dark p-3 flex gap-3 items-center"><span className="w-10 h-10 rounded-full border border-white/20" style={{ background: '#' + binding.color_hex.slice(0, 6) }} /><div><p className="text-white font-semibold">{binding.virtual_printer_name || binding.printer_name || '未命名打印机'}</p><p className="text-bambu-gray">{binding.material} · {binding.color_name || binding.color_hex} · 扫描码 {binding.scan_code}</p><p className="text-xs text-bambu-gray">直供耗材 · {new Date(binding.scanned_at).toLocaleString()}</p></div></div>)}</div>}</CardContent></Card>
    {cameraOpen && <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"><div className="w-full max-w-md rounded-xl bg-bambu-dark-secondary border border-bambu-gray-dark p-4 space-y-3"><div className="flex justify-between items-center"><h2 className="text-white font-semibold">摄像头扫码</h2><button type="button" aria-label="关闭摄像头扫码" onClick={() => setCameraOpen(false)} className="text-bambu-gray hover:text-white"><X size={20} /></button></div><video ref={videoRef} muted playsInline className="w-full aspect-square rounded-lg bg-black object-cover" /><p className="text-sm text-bambu-gray">将材料二维码放入取景框。若浏览器不支持识别，请使用扫码枪或手动输入。</p></div></div>}
  </div>;
}
