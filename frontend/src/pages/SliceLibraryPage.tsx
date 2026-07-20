import { useQuery } from '@tanstack/react-query';
import { Download, LibraryBig } from 'lucide-react';
import { productionApi } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';

export function SliceLibraryPage() {
  const { data: artifacts = [], isLoading, error } = useQuery({
    queryKey: ['slice-artifacts'],
    queryFn: productionApi.listSliceArtifacts,
  });

  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <div>
      <h1 className="text-3xl font-bold text-white flex items-center gap-3"><LibraryBig className="text-bambu-green" />切片库</h1>
      <p className="text-bambu-gray mt-2">真实切片成功后自动保存。相同源文件版本、摆盘策略和打印机参数会直接复用，不会重复切片。</p>
      <p className="text-amber-300 text-sm mt-2">阶段14前禁止发送真实打印；这里可以查看和下载已生成的 G-code 3MF。</p>
    </div>
    {isLoading && <Card><CardContent className="text-bambu-gray">正在读取切片库…</CardContent></Card>}
    {error && <Card><CardContent className="text-red-400">切片库读取失败：{error instanceof Error ? error.message : '未知错误'}</CardContent></Card>}
    {!isLoading && !error && artifacts.length === 0 && <Card><CardContent className="text-center py-16 text-bambu-gray">还没有成功的真实切片结果。请在生产订单中运行真实切片。</CardContent></Card>}
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
          <Button variant="secondary" onClick={() => productionApi.downloadSliceArtifact(artifact.id)}><Download size={16} />下载切片文件</Button>
        </CardContent>
      </Card>)}
    </div>
  </div>;
}
