import { request } from './client';
export interface PrinterProfile { id:number;code:string;name:string;printer_model:string;nozzle_diameter:number;version:number;location?:string|null;profile_group?:string|null;auto_production_enabled:boolean;is_active:boolean }
export interface ProductionRecipe { id:number;code:string;name:string;product_id:number;material_type_id?:number|null;printer_profile_id?:number|null;library_file_id?:number|null;slicer_pipeline_id?:number|null;slicer_preset?:string|null;compatible_profile_ids:number[];version:number;is_active:boolean }
export const productionRecipesApi={
 profiles:()=>request<PrinterProfile[]>('/production/printer-profiles'),
 createProfile:(data:Omit<PrinterProfile,'id'>)=>request<PrinterProfile>('/production/printer-profiles',{method:'POST',body:JSON.stringify(data)}),
 updateProfile:(id:number,data:Omit<PrinterProfile,'id'>)=>request<PrinterProfile>(`/production/printer-profiles/${id}`,{method:'PUT',body:JSON.stringify(data)}),
 deleteProfile:(id:number)=>request<void>(`/production/printer-profiles/${id}`,{method:'DELETE'}),
 recipes:()=>request<ProductionRecipe[]>('/production/recipes'),
 createRecipe:(data:Omit<ProductionRecipe,'id'>)=>request<ProductionRecipe>('/production/recipes',{method:'POST',body:JSON.stringify(data)}),
};
