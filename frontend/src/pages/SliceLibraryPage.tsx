import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, LibraryBig, Send } from 'lucide-react';
import { api, type Printer } from '../api/client';
import { productionApi, type SliceArtifact } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { ConfirmModal } from '../components/ConfirmModal';

export function SliceLibraryPage() {
  const queryClient = useQueryClient();
  const [candidate, setCandidate] = useState<SliceArtifact | null>(null);
  const [printerId, setPrinterId] = useState<number | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);
  const { data: artifacts = [], isLoading, error } = useQuery({
    queryKey: ['slice-artifacts'],
    queryFn: productionApi.listSliceArtifacts,
  });
  const { data: printers = [] } = useQuery({
    queryKey: ['printers'],
    queryFn: () => api.getPrinters(),
  });
  const activePrinters = printers.filter(printer => printer.is_active);
  const dispatch = useMutation({
    mutationFn: () => productionApi.dispatchSliceArtifact(candidate!.id, { printer_id: printerId! }),
    onSuccess: result => {
      setResultMessage(`已将切片 #${result.artifact_id} 加入 ${result.printer_name} 的真实打印队列（队列 #${result.queue_item_id}）。打印机确认开始后，生产任务会自动进入“打印中”；完成后进入“待质检”。`);
      setCandidate(null);
      queryClient.invalidateQueries({ queryKey: ['slice-artifacts'] });
      queryClient.invalidateQueries({ queryKey: ['production-printer-status'] });
    },
  });

  const beginDispatch = (artifact: SliceArtifact) => {
    setResultMessage(null);
    setCandidate(artifact);
    setPrinterId(activePrinters[0]?.id ?? null);
  };

  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <div>
      <h1 className="text-3xl font-bold text-white flex items-center gap-3"><LibraryBig className="text-bambu-green" />切片库</h1>
      <p className="text-bambu-gray mt-2">真实切片成功后自动保存。相同源文件版本、摆盘策略和打印机参数会直接复用，不会重复切片。</p>
      <p className="text-amber-300 text-sm mt-2">生产订单在真实打印机在线、型号和已扫码耗材匹配、切片成功且机器空闲时会自动进入原有队列。本页用于手动发送独立切片结果；不会发送到虚拟打印机。</p>
    </div>
    {resultMessage && <Card className="border-bambu-green/50"><CardContent className="py-4 text-bambu-green">{resultMessage}</CardContent></Card>}
    {isLoading && <Card><CardContent className="text-bambu-gray">正在读取切片库…</CardContent></Card>}
    {error && <Card><CardContent className="text-red-400">切片库读取失败：{error instanceof Error ? error.message : '未知错误'}</CardContent></Card>}
    {!isLoading && !error && artifacts.length === 0 && <Card><CardContent className="text-center py-16 text-bambu-gray">还没有成功的真实切片结果。请先在生产订单中运行真实切片。</CardContent></Card>}
    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
      {artifacts.map(artifact => <Card key={artifact.id}>
        <CardContent className="space-y-3">
          <div className="flex justify-between gap-3"><span className="text-bambu-green font-mono">切片 #{artifact.id}</span><span className="text-white">{artifact.strategy === 'auto_pack' ? '自动摆盘' : '固定摆盘'}</span></div>
          <div className="text-sm text-bambu-gray space-y-1">
            <p>输出文件：{artifact.output_file_name || `切片文件 #${artifact.output_library_file_id}`}</p>
            <p>源文件 ID：{artifact.source_library_file_id} · v{artifact.source_version}</p>
            <p>目标打印机：{artifact.target_printer_model || artifact.target_printer_preset || '沿用源文件'}</p>
            {artifact.print_time_seconds != null && <p>预计用时：{Math.round(artifact.print_time_seconds / 60)} 分钟</p>}
            {artifact.filament_used_g != null && <p>耗材：{artifact.filament_used_g.toFixed(1)} g</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => productionApi.downloadSliceArtifact(artifact.id)}><Download size={16} />下载切片文件</Button>
            <Button onClick={() => beginDispatch(artifact)} disabled={!activePrinters.length}><Send size={16} />发送到真实打印机</Button>
          </div>
          {!activePrinters.length && <p className="text-xs text-amber-300">请先在“打印机”页面添加并连接一台真实打印机。</p>}
        </CardContent>
      </Card>)}
    </div>
    {candidate && <DispatchConfirmation
      artifact={candidate}
      printers={activePrinters}
      printerId={printerId}
      onPrinterChange={setPrinterId}
      error={dispatch.error}
      isLoading={dispatch.isPending}
      onCancel={() => !dispatch.isPending && setCandidate(null)}
      onConfirm={() => dispatch.mutate()}
    />}
  </div>;
}

function DispatchConfirmation({ artifact, printers, printerId, onPrinterChange, error, isLoading, onCancel, onConfirm }: {
  artifact: SliceArtifact; printers: Printer[]; printerId: number | null; onPrinterChange: (value: number | null) => void;
  error: unknown; isLoading: boolean; onCancel: () => void; onConfirm: () => void;
}) {
  const selected = printers.find(printer => printer.id === printerId);
  return <ConfirmModal
    title="确认发送到真实打印机"
    message={`将切片 #${artifact.id} 交给真实打印机执行。系统只会发送这一次已选择的切片，不会自动选择其他打印机。打印机接收后会按原有队列通过 MQTT/FTP 上传并开始打印。`}
    confirmText="确认进入真实打印队列"
    variant="warning"
    isLoading={isLoading}
    confirmDisabled={!selected}
    onCancel={onCancel}
    onConfirm={onConfirm}
  >
    <label className="block text-sm text-bambu-gray">真实打印机
      <select value={printerId ?? ''} onChange={event => onPrinterChange(event.target.value ? Number(event.target.value) : null)} className="mt-2 w-full rounded-lg border border-bambu-gray-dark bg-bambu-dark px-3 py-2 text-white">
        <option value="">请选择</option>
        {printers.map(printer => <option value={printer.id} key={printer.id}>{printer.name} · {printer.model || '未指定型号'} · {printer.ip_address}</option>)}
      </select>
    </label>
    {selected && <p className="mt-3 text-xs text-amber-300">将发送到：{selected.name}。如果该机未连接、离线或故障，系统会拒绝发送，不会改用其他机器。</p>}
    {error ? <p className="mt-3 text-sm text-red-300">发送未执行：{error instanceof Error ? error.message : String(error)}</p> : null}
  </ConfirmModal>;
}
