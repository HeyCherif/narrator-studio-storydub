import {beforeEach,expect,test} from 'vitest';
import {mountStudio} from '../src/screens/studio';
import type {NarratorClient} from '../src/types';

beforeEach(()=>{document.body.innerHTML='<div id="app"></div>';localStorage.clear();});
const tick=()=>new Promise(r=>setTimeout(r,0));
function client(ready=true){
 let event:(value:any)=>void=()=>{};
 const fake={bootstrap:async()=>({runtime:{python_exists:ready,model_exists:ready},voices:[{id:'voice1',name:'Voice 1'}],active_engine:'omnivoice'}),generate:async()=>({job_id:'job1'}),cancelGenerate:async()=>({ok:true}),subscribeRuntime:(fn:any)=>{event=fn;return()=>{};},emit:(data:any)=>event(data)};
 return fake;
}

test('missing runtime prevents generation and explains setup',async()=>{
 mountStudio(document.querySelector('#app')!,client(false) as unknown as NarratorClient);await tick();
 const button=document.querySelector<HTMLButtonElement>('[data-generate]')!;
 expect(button.disabled).toBe(true);expect(document.body.textContent).toContain('Modèles');
});

test('accepted generation disables repeated submits and ignores an old job',async()=>{
 const fake=client();mountStudio(document.querySelector('#app')!,fake as unknown as NarratorClient);await tick();
 const text=document.querySelector<HTMLTextAreaElement>('textarea')!;text.value='A short narration.';text.dispatchEvent(new Event('input'));
 const button=document.querySelector<HTMLButtonElement>('[data-generate]')!;button.click();await tick();
 expect(button.disabled).toBe(true);
 fake.emit({event:'job',job_id:'old-job',payload:{running:false,stage:'Wrong stale result'}});await tick();
 expect(document.body.textContent).not.toContain('Wrong stale result');expect(button.disabled).toBe(true);
 fake.emit({event:'job',job_id:'job1',payload:{running:false,stage:'Completed'}});await tick();
 expect(button.disabled).toBe(false);
});

test('draft survives remounting the screen',async()=>{
 const destroy=mountStudio(document.querySelector('#app')!,client() as unknown as NarratorClient);await tick();
 const text=document.querySelector<HTMLTextAreaElement>('textarea')!;text.value='Keep this draft';text.dispatchEvent(new Event('input'));destroy();
 mountStudio(document.querySelector('#app')!,client() as unknown as NarratorClient);await tick();
 expect(document.querySelector('textarea')!.value).toBe('Keep this draft');
});

test('returning to Studio restores the completed narration player',async()=>{
 const fake={...client(),bootstrap:async()=>({runtime:{python_exists:true,model_exists:true},voices:[],active_engine:'omnivoice',job_id:'finished',job:{running:false,stage:'Finished',progress:100,result:{filename:'finished.wav'}}}),audioUrl:async()=>'/finished.wav'};
 mountStudio(document.querySelector('#app')!,fake as unknown as NarratorClient);await tick();await tick();
 expect(document.querySelector('audio')?.getAttribute('src')).toBe('/finished.wav');
 expect(document.querySelector('[data-stage]')!.textContent).toBe('Finished');
});
