export function escape(value:unknown){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));}
export function icon(name:string){return `<i class="ti ti-${name}" aria-hidden="true"></i>`;}
export function showError(target:HTMLElement,error:unknown){target.textContent=String(error instanceof Error?error.message:error);target.classList.add('error-message');}
export function title(kicker:string,heading:string,hint:string){return `<header class="page-heading"><div class="eyebrow">${escape(kicker)}</div><h1>${escape(heading)}</h1><p>${escape(hint)}</p></header>`;}
