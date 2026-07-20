import { getAuthToken, request } from './client';

export interface ProductFile { id:number; product_id:number; library_file_id:number; name:string; product_color?:string|null; strategy:'fixed_plate'|'auto_pack'|'multi_plate_fixed'; component_ids:number[]; units_per_plate:number; source_plate_count:number; source_set_id?:string|null; source_plate_index:number; compatible_printer_models:string[]; filament_requirements:Array<{slot:number;material:string;color:string}>; version:number; is_active:boolean }
export interface Product { id:number; sku:string; name:string; description?:string|null; size_class:'standard'|'large'; production_mode:'single_plate'|'multi_plate'; source_plate_count:number; is_active:boolean; images?:ProductImage[]; bom_items?:BOMItem[]; product_files?:ProductFile[] }
export interface ProductImage { id:number; product_id:number; original_name:string; content_type:string; file_size:number; is_primary:boolean; sort_order:number }
export interface Component { id:number; code:string; name:string; description?:string|null; unit:string; is_active:boolean }
export interface BOMItem { id:number; product_id:number; component_id:number; quantity:number; notes?:string|null }
export type ProductInput = Pick<Product, 'name'> & Partial<Pick<Product,'sku'|'description'|'size_class'|'production_mode'|'source_plate_count'|'is_active'>>;

const authHeaders = (): Record<string,string> => {
  const token=getAuthToken();
  return token ? {Authorization:`Bearer ${token}`} : {};
};

const responseError = async (response:Response, fallback:string) => {
  const body=await response.json().catch(()=>({}));
  const detail = body.detail;
  if (response.status === 503 || detail === 'Authentication service temporarily unavailable') return new Error('后端服务暂时不可用，请重启当前 Bambuddy 后端后重试。');
  if (response.status === 401) return new Error('当前登录已失效，请重新登录后再上传。');
  return new Error(detail||fallback);
};

export const productsApi = {
  list: () => request<Product[]>('/products'),
  get: (id:number) => request<Product>(`/products/${id}`),
  create: (data:ProductInput) => request<Product>('/products', {method:'POST', body:JSON.stringify(data)}),
  createWithImage: async (name:string, description:string, file:File, structure:{production_mode:'single_plate'|'multi_plate';source_plate_count:number}) => { const form=new FormData(); form.append('name',name); form.append('description',description); form.append('production_mode',structure.production_mode); form.append('source_plate_count',String(structure.source_plate_count)); form.append('file',file); const response=await fetch('/api/v1/products/with-image',{method:'POST',body:form,headers:authHeaders()}); if(!response.ok) throw await responseError(response,'产品创建失败'); return response.json() as Promise<Product>; },
  update: (id:number, data:Partial<ProductInput>) => request<Product>(`/products/${id}`, {method:'PUT', body:JSON.stringify(data)}),
  remove: (id:number) => request<void>(`/products/${id}`, {method:'DELETE'}),
  components: () => request<Component[]>('/products/components'),
  createComponent: (data:Omit<Component,'id'>) => request<Component>('/products/components', {method:'POST', body:JSON.stringify(data)}),
  addBom: (id:number, data:{component_id:number;quantity:number;notes?:string}) => request<BOMItem>(`/products/${id}/bom`, {method:'POST', body:JSON.stringify(data)}),
  deleteBom: (id:number,itemId:number) => request<void>(`/products/${id}/bom/${itemId}`, {method:'DELETE'}),
  uploadImage: async (id:number,file:File) => { const form=new FormData(); form.append('file',file); const response=await fetch(`/api/v1/products/${id}/images`,{method:'POST',body:form,headers:authHeaders()}); if(!response.ok) throw await responseError(response,'Upload failed'); return response.json() as Promise<ProductImage>; },
  uploadProductFile: async (id:number,file:File,options:{strategy:'fixed_plate'|'auto_pack'|'multi_plate_fixed';units_per_plate:number;component_ids:number[];compatible_printer_models:string[];filament_requirements:Array<{slot:number;material:string;color:string}>;product_color?:string;source_set_id?:string;source_plate_index?:number}) => { const form=new FormData(); form.append('file',file); form.append('strategy',options.strategy); form.append('units_per_plate',String(options.units_per_plate)); form.append('component_ids',JSON.stringify(options.component_ids)); form.append('compatible_printer_models',JSON.stringify(options.compatible_printer_models)); form.append('filament_requirements',JSON.stringify(options.filament_requirements)); form.append('product_color',options.product_color || ''); if(options.source_set_id) form.append('source_set_id',options.source_set_id); if(options.source_plate_index !== undefined) form.append('source_plate_index',String(options.source_plate_index)); const response=await fetch(`/api/v1/products/${id}/files`,{method:'POST',body:form,headers:authHeaders()}); if(!response.ok) throw await responseError(response,'Product file upload failed'); return response.json() as Promise<ProductFile>; },
  deleteProductFile: (id:number, fileId:number) => request<void>(`/products/${id}/files/${fileId}`, {method:'DELETE'}),
  deactivateProductFile: (id:number, fileId:number) => request<void>(`/products/${id}/files/${fileId}/deactivate`, {method:'POST'}),
  importArchive: async (file:File) => { const form=new FormData(); form.append('file',file); const response=await fetch('/api/v1/products/import/archive',{method:'POST',body:form,headers:authHeaders()}); if(!response.ok) throw await responseError(response,'Import failed'); return response.json() as Promise<Product>; },
  getImageBlob: async (id:number,imageId:number) => { const response=await fetch(`/api/v1/products/${id}/images/${imageId}/file`,{headers:authHeaders()}); if(!response.ok) throw await responseError(response,'Image load failed'); return response.blob(); },
  exportArchive: async (id:number) => { const response=await fetch(`/api/v1/products/${id}/export`,{headers:authHeaders()}); if(!response.ok) throw await responseError(response,'Export failed'); const disposition=response.headers.get('Content-Disposition'); const filename=disposition?.match(/filename="?([^";]+)"?/)?.[1]||`product-${id}.bambuddy-product.zip`; return {blob:await response.blob(),filename}; },
};
