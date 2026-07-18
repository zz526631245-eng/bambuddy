import { getAuthToken, request } from './client';

export interface Product { id:number; sku:string; name:string; description?:string|null; is_active:boolean; images?:ProductImage[]; bom_items?:BOMItem[] }
export interface ProductImage { id:number; product_id:number; original_name:string; content_type:string; file_size:number; is_primary:boolean; sort_order:number }
export interface Component { id:number; code:string; name:string; description?:string|null; unit:string; is_active:boolean }
export interface BOMItem { id:number; product_id:number; component_id:number; quantity:number; notes?:string|null }
export type ProductInput = Pick<Product, 'sku'|'name'> & Partial<Pick<Product,'description'|'is_active'>>;

export const productsApi = {
  list: () => request<Product[]>('/products'),
  get: (id:number) => request<Product>(`/products/${id}`),
  create: (data:ProductInput) => request<Product>('/products', {method:'POST', body:JSON.stringify(data)}),
  update: (id:number, data:Partial<ProductInput>) => request<Product>(`/products/${id}`, {method:'PUT', body:JSON.stringify(data)}),
  remove: (id:number) => request<void>(`/products/${id}`, {method:'DELETE'}),
  components: () => request<Component[]>('/products/components'),
  createComponent: (data:Omit<Component,'id'>) => request<Component>('/products/components', {method:'POST', body:JSON.stringify(data)}),
  addBom: (id:number, data:{component_id:number;quantity:number;notes?:string}) => request<BOMItem>(`/products/${id}/bom`, {method:'POST', body:JSON.stringify(data)}),
  deleteBom: (id:number,itemId:number) => request<void>(`/products/${id}/bom/${itemId}`, {method:'DELETE'}),
  uploadImage: async (id:number,file:File) => { const form=new FormData(); form.append('file',file); const headers:Record<string,string>={}; const token=getAuthToken(); if(token) headers.Authorization=`Bearer ${token}`; const response=await fetch(`/api/v1/products/${id}/images`,{method:'POST',body:form,headers}); if(!response.ok) throw new Error((await response.json()).detail||'Upload failed'); return response.json() as Promise<ProductImage>; },
  importArchive: async (file:File) => { const form=new FormData(); form.append('file',file); const headers:Record<string,string>={}; const token=getAuthToken(); if(token) headers.Authorization=`Bearer ${token}`; const response=await fetch('/api/v1/products/import/archive',{method:'POST',body:form,headers}); if(!response.ok) throw new Error((await response.json()).detail||'Import failed'); return response.json() as Promise<Product>; },
  imageUrl: (id:number,imageId:number) => `/api/v1/products/${id}/images/${imageId}/file`,
  exportUrl: (id:number) => `/api/v1/products/${id}/export`,
};
