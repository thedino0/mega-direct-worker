function constantTimeEqual(left,right){if(typeof left!=="string"||typeof right!=="string"||left.length!==right.length){return false}let difference=0;for(let i=0;i<left.length;i++){difference|=left.charCodeAt(i)^right.charCodeAt(i)}return difference===0}function checkWorkerKey(request,env){const expected=env&&env.WORKER_KEY;if(typeof expected!=="string"||expected.length===0){return{ok:false,status:503,code:"worker_key_missing",message:"Worker key is not configured."}}const provided=request.headers.get("x-key")||"";if(!constantTimeEqual(provided,expected)){return{ok:false,status:401,code:"unauthorized",message:"Worker key was not accepted."}}return{ok:true}}var DEBUG=true;var EXPIRES_IN=1200;var MEGA_API="https://g.api.mega.co.nz/cs";var HANDLE_RE=/^[A-Za-z0-9_-]{8}$/;var FILE_KEY_RE=/^[A-Za-z0-9_-]{43}$/;var FOLDER_KEY_RE=/^[A-Za-z0-9_-]{22}$/;var ALLOWED_HOSTS=new Set(["mega.nz","mega.io","mega.co.nz"]);var MAX_FOLDER_NODES=1e4;var MAX_FOLDER_FILES=2e3;var MAX_BATCH=100;var MAX_API_BYTES=8*1024*1024;var MAX_INPUT=4096;var CORS_HEADERS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET, POST, OPTIONS","Access-Control-Allow-Headers":"Content-Type, X-Key"};function jsonResponse(body,status=200){return new Response(JSON.stringify(body),{status,headers:{...CORS_HEADERS,"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}})}function optionsResponse(){return new Response(null,{status:204,headers:CORS_HEADERS})}function log(stage,fields={}){if(DEBUG)console.log(JSON.stringify({stage,...fields}))}function logError(stage,fields={}){console.error(JSON.stringify({stage,...fields}))}var WorkerError=class extends Error{constructor(code,message,status,megaCode=null){super(message);this.code=code;this.status=status;this.megaCode=megaCode}};function gmul(a,b){let product=0;let left=a;let right=b;for(let i=0;i<8;i++){if(right&1)product^=left;const high=left&128;left=left<<1&255;if(high)left^=27;right>>=1}return product&255}function gfPow(base,exponent){if(base===0)return 0;let result=1;let value=base;let power=exponent;while(power>0){if(power&1)result=gmul(result,value);value=gmul(value,value);power>>=1}return result}function rotl8(value,amount){return(value<<amount|value>>>8-amount)&255}var SBOX=new Uint8Array(256);var INV_SBOX=new Uint8Array(256);for(let i=0;i<256;i++){const inverse=i===0?0:gfPow(i,254);const substituted=(inverse^rotl8(inverse,1)^rotl8(inverse,2)^rotl8(inverse,3)^rotl8(inverse,4)^99)&255;SBOX[i]=substituted;INV_SBOX[substituted]=i}function expandKey(key){const schedule=new Uint8Array(176);schedule.set(key);let rcon=1;for(let offset=16;offset<176;offset+=4){let b0=schedule[offset-4];let b1=schedule[offset-3];let b2=schedule[offset-2];let b3=schedule[offset-1];if(offset%16===0){const first=b0;b0=SBOX[b1]^rcon;b1=SBOX[b2];b2=SBOX[b3];b3=SBOX[first];rcon=gmul(rcon,2)}schedule[offset]=schedule[offset-16]^b0;schedule[offset+1]=schedule[offset-15]^b1;schedule[offset+2]=schedule[offset-14]^b2;schedule[offset+3]=schedule[offset-13]^b3}return schedule}function addRoundKey(state,schedule,offset){for(let i=0;i<16;i++)state[i]^=schedule[offset+i]}function invShiftRows(state){const copy=state.slice();for(let row=1;row<4;row++){for(let column=0;column<4;column++){state[row+4*((column+row)%4)]=copy[row+4*column]}}}function invSubBytes(state){for(let i=0;i<16;i++)state[i]=INV_SBOX[state[i]]}function invMixColumns(state){for(let column=0;column<4;column++){const offset=column*4;const a0=state[offset];const a1=state[offset+1];const a2=state[offset+2];const a3=state[offset+3];state[offset]=gmul(a0,14)^gmul(a1,11)^gmul(a2,13)^gmul(a3,9);state[offset+1]=gmul(a0,9)^gmul(a1,14)^gmul(a2,11)^gmul(a3,13);state[offset+2]=gmul(a0,13)^gmul(a1,9)^gmul(a2,14)^gmul(a3,11);state[offset+3]=gmul(a0,11)^gmul(a1,13)^gmul(a2,9)^gmul(a3,14)}}function decryptBlock(block,schedule){const state=new Uint8Array(block);addRoundKey(state,schedule,160);for(let round=9;round>=1;round--){invShiftRows(state);invSubBytes(state);addRoundKey(state,schedule,round*16);invMixColumns(state)}invShiftRows(state);invSubBytes(state);addRoundKey(state,schedule,0);return state}function aes128CbcDecrypt(key,ciphertext){const schedule=expandKey(key);const output=new Uint8Array(ciphertext.length);let previous=new Uint8Array(16);for(let offset=0;offset<ciphertext.length;offset+=16){const current=ciphertext.subarray(offset,offset+16);const plain=decryptBlock(current,schedule);for(let i=0;i<16;i++)output[offset+i]=plain[i]^previous[i];previous=current}return output}function aes128EcbDecrypt(key,ciphertext){const schedule=expandKey(key);const output=new Uint8Array(ciphertext.length);for(let offset=0;offset<ciphertext.length;offset+=16){output.set(decryptBlock(ciphertext.subarray(offset,offset+16),schedule),offset)}return output}function b64urlToBytes(value){const normalized=value.replace(/-/g,"+").replace(/_/g,"/");const padded=normalized+"=".repeat((4-normalized.length%4)%4);const binary=atob(padded);const bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);return bytes}function deriveFileKey(fragment){let raw;try{raw=b64urlToBytes(fragment)}catch{throw new WorkerError("invalid_key","The link decryption key is malformed.",400)}if(raw.length!==32){throw new WorkerError("invalid_key","The link decryption key has the wrong length.",400)}const key=new Uint8Array(16);for(let i=0;i<16;i++)key[i]=raw[i]^raw[i+16];return key}function deriveFolderKey(fragment){let raw;try{raw=b64urlToBytes(fragment)}catch{throw new WorkerError("invalid_key","The link decryption key is malformed.",400)}if(raw.length!==16){throw new WorkerError("invalid_key","The link decryption key has the wrong length.",400)}return raw}function extensionOf(name){const dot=name.lastIndexOf(".");if(dot<=0||dot===name.length-1)return"";return name.slice(dot+1).toLowerCase()}function decryptAttrs(encoded,key){let ciphertext;try{ciphertext=b64urlToBytes(encoded)}catch{throw new WorkerError("decrypt_failed","MEGA sent metadata we could not decrypt.",502)}if(ciphertext.length===0||ciphertext.length%16!==0){throw new WorkerError("decrypt_failed","MEGA sent metadata we could not decrypt.",502)}const plaintext=aes128CbcDecrypt(key,ciphertext);if(plaintext[0]!==77||plaintext[1]!==69||plaintext[2]!==71||plaintext[3]!==65){throw new WorkerError("decrypt_failed","The decryption key does not match this link.",400)}let end=plaintext.length;while(end>4&&plaintext[end-1]===0)end--;let attrs;try{const text=new TextDecoder().decode(plaintext.subarray(4,end));attrs=JSON.parse(text)}catch{throw new WorkerError("decrypt_failed","MEGA sent metadata we could not read.",502)}if(!attrs||typeof attrs!=="object"){throw new WorkerError("decrypt_failed","MEGA sent metadata we could not read.",502)}return attrs}function nodeAttrKey(nodeKey,type){if(type===1)return nodeKey;const key=new Uint8Array(16);for(let i=0;i<16;i++)key[i]=nodeKey[i]^nodeKey[i+16];return key}function selectNodeKey(node,rootHandle){if(typeof node.k!=="string"){throw new WorkerError("decrypt_failed","MEGA sent a node without a key.",502)}const alternatives=node.k.split("/");let selected=alternatives.find(alt=>alt.slice(0,8)===rootHandle&&alt[8]===":");if(!selected){selected=alternatives.find(alt=>alt.slice(0,8)===node.h&&alt[8]===":")}if(!selected){if(alternatives.length===1){selected=alternatives[0]}else{throw new WorkerError("decrypt_failed","MEGA sent an unexpected node key.",502)}}const colon=selected.indexOf(":");if(colon<=0||colon===selected.length-1){throw new WorkerError("decrypt_failed","MEGA sent an unexpected node key.",502)}return selected.slice(colon+1)}function decryptNodeKey(node,linkKey,rootHandle){const encoded=selectNodeKey(node,rootHandle);let ciphertext;try{ciphertext=b64urlToBytes(encoded)}catch{throw new WorkerError("decrypt_failed","MEGA sent metadata we could not decrypt.",502)}const expected=node.t===1?16:32;if(ciphertext.length!==expected){throw new WorkerError("decrypt_failed","MEGA sent metadata we could not decrypt.",502)}return aes128EcbDecrypt(linkKey,ciphertext)}function findPublicRoot(nodes){const handles=new Set(nodes.map(node=>node.h));const selfKeyed=nodes.find(node=>typeof node.k==="string"&&node.k.split("/").some(alt=>alt.slice(0,8)===node.h&&alt[8]===":"));if(selfKeyed)return selfKeyed;const orphan=nodes.find(node=>!handles.has(node.p));if(orphan)return orphan;throw new WorkerError("bad_response","MEGA did not return a folder root.",502)}function findFolderRoot(nodes,startHandle){if(!startHandle)return findPublicRoot(nodes);const selected=nodes.find(node=>node.h===startHandle&&node.t===1);if(!selected){throw new WorkerError("not_found","That subfolder is not in this folder.",404)}return selected}function compareEntries(a,b){if(a.isFolder!==b.isFolder)return a.isFolder?-1:1;const left=a.name.toLowerCase();const right=b.name.toLowerCase();if(left<right)return-1;if(left>right)return 1;return 0}function buildFolderIndex(nodes,linkKey,startHandle=null){const publicRoot=findPublicRoot(nodes);const root=findFolderRoot(nodes,startHandle);const entries=new Map;for(const node of nodes){if(node.t!==0&&node.t!==1)continue;if(typeof node.h!=="string"||!HANDLE_RE.test(node.h))continue;const nodeKey=decryptNodeKey(node,linkKey,publicRoot.h);let name=node.h;if(typeof node.a==="string"&&node.a.length>0){const attrs=decryptAttrs(node.a,nodeAttrKey(nodeKey,node.t));if(typeof attrs.n==="string"&&attrs.n.length>0)name=attrs.n}let size=0;if(node.t===0){size=Number(node.s);if(!Number.isSafeInteger(size)||size<0){throw new WorkerError("bad_response","MEGA sent an invalid file size.",502)}}entries.set(node.h,{handle:node.h,parent:node.p,name,isFolder:node.t===1,size,children:[]})}const rootEntry=entries.get(root.h);if(!rootEntry){throw new WorkerError("bad_response","MEGA did not return a folder root.",502)}for(const entry of entries.values()){if(entry.handle===root.h)continue;const parent=entries.get(entry.parent);if(parent&&parent.isFolder)parent.children.push(entry);else if(root.handle===publicRoot.h)rootEntry.children.push(entry)}const files=[];const seen=new Set([root.h]);function walk(folder,path,depth){if(depth>64){throw new WorkerError("folder_too_large","That folder is nested too deeply.",413)}folder.children.sort(compareEntries);for(const child of folder.children){if(seen.has(child.handle))continue;seen.add(child.handle);const childPath=path?`${path}/${child.name}`:child.name;if(child.isFolder)walk(child,childPath,depth+1);else files.push({node:child,path:childPath})}}walk(rootEntry,"",0);files.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);return{root:rootEntry,files}}function mapMegaError(code){switch(code){case-1:return["mega_internal","MEGA had an internal error.",502];case-2:return["mega_rejected","MEGA rejected the request.",502];case-3:return["busy","MEGA is busy. Try again in a moment.",503];case-4:case-6:case-19:return["rate_limited","MEGA is rate-limiting requests. Try again shortly.",429];case-5:case-25:return["mega_failed","MEGA could not complete the request.",502];case-7:case-10:case-12:return["mega_rejected","MEGA rejected the request.",502];case-8:return["expired","That MEGA link has expired.",410];case-9:return["not_found","That MEGA link is dead or wrong.",404];case-11:return["access_denied","MEGA denied access to that link.",403];case-13:return["incomplete","That link is incomplete on MEGA.",409];case-14:return["decrypt_failed","The decryption key does not match this link.",400];case-15:return["session_error","MEGA rejected the session.",502];case-16:return["blocked","MEGA blocked that link.",403];case-17:case-24:return["quota_exceeded","MEGA transfer quota is exhausted for this link.",429];case-18:return["unavailable","MEGA says that link is temporarily unavailable.",503];default:return["mega_error","MEGA refused the request.",502]}}var sequence=1+Math.floor(Math.random()*999999999);function nextSequence(){sequence=sequence%999999999+1;return String(sequence)}async function megaApi({query="",body,cmd,count=1,maxBytes=MAX_API_BYTES}){const id=nextSequence();const started=Date.now();log("api_request",{cmd,id,count});let response;try{response=await fetch(`${MEGA_API}?id=${id}${query}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})}catch{throw new WorkerError("upstream_unreachable","MEGA did not answer. Try again.",502)}let text;try{text=await response.text()}catch{throw new WorkerError("bad_response","MEGA returned an unreadable response.",502)}log("api_response",{cmd,status:response.status,ms:Date.now()-started,bytes:text.length});if(response.status===509){throw new WorkerError("quota_exceeded","MEGA transfer quota is exhausted for this link.",429)}if(!response.ok){throw new WorkerError("upstream_error","MEGA returned an error. Try again.",502)}if(text.length>maxBytes){throw new WorkerError("bad_response","MEGA returned an oversized response.",502)}let payload;try{payload=JSON.parse(text)}catch{throw new WorkerError("bad_response","MEGA returned an unreadable response.",502)}if(!Array.isArray(payload)||payload.length===0){throw new WorkerError("bad_response","MEGA returned an empty response.",502)}const first=payload[0];if(typeof first==="number"){const[code,message,status]=mapMegaError(first);throw new WorkerError(code,message,status,first)}return payload}async function fetchMegaFile(handle){const payload=await megaApi({body:[{a:"g",g:1,p:handle,ssl:2}],cmd:"g"});const item=payload[0];if(!item||typeof item!=="object"){throw new WorkerError("bad_response","MEGA returned an unexpected response.",502)}return item}async function fetchFolderNodes(handle){const payload=await megaApi({query:`&n=${encodeURIComponent(handle)}`,body:[{a:"f",c:1,r:1,ca:1}],cmd:"f"});const item=payload[0];if(!item||typeof item!=="object"){throw new WorkerError("bad_response","MEGA returned an unexpected response.",502)}const nodes=Array.isArray(item.f)?item.f:[];if(nodes.length>MAX_FOLDER_NODES){throw new WorkerError("folder_too_large","That folder has too many entries.",413)}log("folder_nodes",{count:nodes.length});return nodes}async function fetchFolderUrls(linkHandle,fileNodes){const urls=new Map;for(let start=0;start<fileNodes.length;start+=MAX_BATCH){const chunk=fileNodes.slice(start,start+MAX_BATCH);const body=chunk.map(node=>({a:"g",g:1,n:node.handle,ssl:2}));const payload=await megaApi({query:`&n=${encodeURIComponent(linkHandle)}`,body,cmd:"g",count:chunk.length,maxBytes:MAX_API_BYTES});chunk.forEach((node,index)=>{const item=payload[index];if(item&&typeof item==="object"&&typeof item.g==="string"&&/^https?:\/\//i.test(item.g)){urls.set(node.handle,item.g)}else{logError("url_error",{handle:node.handle,megaCode:typeof item==="number"?item:null})}})}return urls}function buildFileResult(link,key,item){if(typeof item.g!=="string"||!/^https?:\/\//i.test(item.g)){throw new WorkerError("bad_response","MEGA did not return a download URL.",502)}const size=Number(item.s);if(!Number.isSafeInteger(size)||size<0){throw new WorkerError("bad_response","MEGA did not return a valid file size.",502)}let name=link.handle;if(typeof item.at==="string"&&item.at.length>0){const attrs=decryptAttrs(item.at,key);if(typeof attrs.n==="string"&&attrs.n.length>0)name=attrs.n;log("attr_decrypt",{ok:true,cipherChars:item.at.length,nameLength:name.length})}else{log("attr_decrypt",{ok:false,reason:"no_attributes"})}const ext=extensionOf(name);log("output",{kind:"file",size,ext,expiresIn:EXPIRES_IN});return{kind:"file",name,size,ext,url:item.g,expires_in:EXPIRES_IN}}async function buildFolderResult(link,key,nodes,startHandle=null){const{root,files}=buildFolderIndex(nodes,key,startHandle);if(files.length>MAX_FOLDER_FILES){throw new WorkerError("folder_too_large","That folder has too many files.",413)}const urls=await fetchFolderUrls(link.handle,files.map(file=>file.node));let total=0;let urlFailures=0;const output=files.map(({node,path})=>{total+=node.size;const url=urls.get(node.handle)||null;if(!url)urlFailures++;return{path,name:node.name,size:node.size,ext:extensionOf(node.name),url,expires_in:url?EXPIRES_IN:null}});log("output",{kind:"folder",files:output.length,size:total,urlFailures,expiresIn:EXPIRES_IN});return{kind:"folder",name:root.name,size:total,file_count:output.length,files:output,expires_in:EXPIRES_IN}}async function buildFolderFileResult(link,key,nodes,fileHandle){const publicRoot=findPublicRoot(nodes);const node=nodes.find(item=>item.h===fileHandle);if(!node||node.t!==0){throw new WorkerError("not_found","That file is not in this folder.",404)}const nodeKey=decryptNodeKey(node,key,publicRoot.h);let name=node.h;if(typeof node.a==="string"&&node.a.length>0){const attrs=decryptAttrs(node.a,nodeAttrKey(nodeKey,node.t));if(typeof attrs.n==="string"&&attrs.n.length>0)name=attrs.n}const size=Number(node.s);if(!Number.isSafeInteger(size)||size<0){throw new WorkerError("bad_response","MEGA sent an invalid file size.",502)}const urls=await fetchFolderUrls(link.handle,[{handle:node.h}]);const url=urls.get(node.h);if(!url){throw new WorkerError("bad_response","MEGA did not return a download URL.",502)}const ext=extensionOf(name);log("output",{kind:"file",size,ext,expiresIn:EXPIRES_IN});return{kind:"file",name,size,ext,url,expires_in:EXPIRES_IN}}function checkInput(value){if(value.length>MAX_INPUT){throw new WorkerError("invalid_url","That link is too long.",400)}return value}function inputFromJson(body){if(typeof body==="string"){return{url:body,key:""}}if(!body||typeof body!=="object"){throw new WorkerError("bad_request","JSON body must be a link or an object with url.",400)}const url=typeof body.url==="string"?body.url:body.link;const key=typeof body.key==="string"?body.key:body.k;return{url:typeof url==="string"?url:"",key:typeof key==="string"?key:""}}async function readInput(request){if(request.method==="GET"){const params=new URL(request.url).searchParams;const raw=params.get("url")??params.get("link");const key=params.get("key")??params.get("k")??"";if(!raw||!raw.trim()){throw new WorkerError("missing_url","Pass a MEGA link as the url query parameter or POST it.",400)}return{url:checkInput(raw.trim()),key:checkInput(key.trim()),keySource:key.trim()?"param":"fragment"}}if(request.method==="POST"){const contentType=(request.headers.get("content-type")||"").toLowerCase();if(contentType.includes("application/json")){let body;try{body=await request.json()}catch{throw new WorkerError("bad_request","POST body must be valid JSON.",400)}const input=inputFromJson(body);if(!input.url.trim()){throw new WorkerError("missing_url","POST body must contain a link.",400)}return{url:checkInput(input.url.trim()),key:checkInput(input.key.trim()),keySource:input.key.trim()?"param":"fragment"}}let text;try{text=await request.text()}catch{throw new WorkerError("bad_request","Could not read the POST body.",400)}if(!text.trim()){throw new WorkerError("missing_url","POST body must contain a link.",400)}let raw=text.trim();let key="";if(contentType.includes("application/x-www-form-urlencoded")&&raw.includes("=")){const form=new URLSearchParams(raw);raw=(form.get("url")??form.get("link")??"").trim();key=(form.get("key")??form.get("k")??"").trim()}if(!raw){throw new WorkerError("missing_url","POST body must contain a link.",400)}return{url:checkInput(raw),key:checkInput(key),keySource:key?"param":"fragment"}}throw new WorkerError("method_not_allowed","Use GET or POST.",405)}function parseMegaLink(input,keyParam=""){let parsed;try{parsed=new URL(input)}catch{throw new WorkerError("invalid_url","That is not a valid link.",400)}const host=parsed.hostname.toLowerCase().replace(/^www\./,"");if(!ALLOWED_HOSTS.has(host)){throw new WorkerError("invalid_url","That is not a MEGA link.",400)}const pathParts=parsed.pathname.split("/").filter(Boolean);if(pathParts.length<2){throw new WorkerError("invalid_url","Expected a MEGA file or folder link.",400)}const kind=pathParts[0].toLowerCase();const handle=pathParts[1];if(kind!=="file"&&kind!=="folder"){throw new WorkerError("invalid_url","Expected a MEGA file or folder link.",400)}if(!HANDLE_RE.test(handle)){throw new WorkerError("invalid_url","The MEGA handle is malformed.",400)}const paramKey=keyParam.startsWith("#")?keyParam.slice(1):keyParam;const urlKey=parsed.hash.startsWith("#")?parsed.hash.slice(1):parsed.hash;const fragment=(paramKey||urlKey).trim();if(!fragment){throw new WorkerError("missing_key","No key reached the worker. HTTP strips #fragments: send key=<key>, encode # as %23, or POST the raw link.",400)}if(fragment.includes("!")){throw new WorkerError("password_protected","Password-protected links are not supported.",400)}const fragmentParts=fragment.split("/");const key=fragmentParts[0];let selection=null;if(kind==="folder"&&fragmentParts.length>=3){const selectionType=fragmentParts[1];const selectionHandle=fragmentParts[2];if(selectionType==="folder"||selectionType==="file"){if(!HANDLE_RE.test(selectionHandle)){throw new WorkerError("invalid_url","The selected MEGA handle is malformed.",400)}selection={type:selectionType,handle:selectionHandle}}}if(kind==="file"){if(!FILE_KEY_RE.test(key)){throw new WorkerError("invalid_key","The link decryption key is malformed.",400)}}else if(!FOLDER_KEY_RE.test(key)){throw new WorkerError("invalid_key","The link decryption key is malformed.",400)}return{kind,handle,key,keySource:paramKey?"param":"fragment",selection}}var UI_HTML=String.raw`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0b0e14">
<title>MEGA Direct</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='15' fill='%236ea8fe'/%3E%3Cpath d='M18 45V19h8l6 9 6-9h8v26h-7V31l-7 10-7-10v14z' fill='%230b0e14'/%3E%3C/svg%3E">
<style>
:root{color-scheme:dark;--bg:#0b0e14;--panel:#121722;--panel2:#171f2d;--line:#243149;--text:#e8eef8;--muted:#8e9bb2;--accent:#6ea8fe;--accent2:#8b5cf6;--danger:#ff7a7a}
*{box-sizing:border-box}
html,body{min-height:100%}
body{margin:0;background:radial-gradient(900px 500px at 20% -10%,#1a2742 0,rgba(11,14,20,0) 60%),var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;line-height:1.5}
a{color:var(--accent)}
.wrap{width:min(900px,100%);margin:0 auto;padding:48px 20px 56px}
.brand{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.mark{width:44px;height:44px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#0b0e14;font-weight:800;font-size:22px;letter-spacing:-.5px;box-shadow:0 10px 30px rgba(110,168,254,.25)}
h1{font-size:clamp(24px,4vw,32px);line-height:1.1;margin:0;letter-spacing:-.03em}
.sub{color:var(--muted);margin:6px 0 26px;font-size:15px}
.panel,.card{background:linear-gradient(180deg,rgba(23,31,45,.96),rgba(18,23,34,.96));border:1px solid var(--line);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.28)}
.panel{padding:18px}
.lookup{display:flex;gap:10px;align-items:stretch}
.lookup .btn{height:48px}
.field{flex:1;min-width:0}
label.sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
input[type=text]{width:100%;height:48px;border-radius:12px;border:1px solid var(--line);background:#0d121b;color:var(--text);padding:0 14px;font-size:15px;outline:none;transition:border-color .15s,box-shadow .15s}
input[type=text]:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(110,168,254,.16)}
input[type=text]::placeholder{color:#5e6b82}
.btn{appearance:none;border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:11px;padding:0 16px;height:44px;font:inherit;font-size:14px;font-weight:650;display:inline-flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;cursor:pointer;transition:transform .12s,background .15s,border-color .15s,filter .15s;white-space:nowrap}
.btn:hover{background:#1d2738;border-color:#334565}
.btn:active{transform:translateY(1px)}
.btn:disabled{opacity:.65;cursor:wait}
.btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;color:#08101d}
.btn.primary:hover{filter:brightness(1.06)}
.btn.ghost{background:transparent}
.btn.small{height:34px;padding:0 11px;font-size:13px;border-radius:9px}
.row{display:flex;gap:9px;align-items:center;margin-top:10px;flex-wrap:wrap}
.hint{color:var(--muted);font-size:13px;margin:10px 0 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#0d121b;border:1px solid var(--line);padding:1px 5px;border-radius:5px;font-size:.92em}
.status{min-height:20px;color:var(--muted);font-size:13px;margin:10px 0 0}
.card{margin-top:18px;padding:20px}
.card.error{border-color:rgba(255,122,122,.42);background:linear-gradient(180deg,rgba(255,122,122,.08),rgba(18,23,34,.96))}
.title{font-size:19px;line-height:1.35;margin:0;word-break:break-word;letter-spacing:-.01em}
.meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.chip{font-size:12px;color:#c1cde2;background:#1c2638;border:1px solid #2a3852;border-radius:999px;padding:3px 9px;white-space:nowrap}
.actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:16px}
.files{margin-top:18px;border-top:1px solid var(--line)}
.file-row{display:flex;gap:14px;align-items:center;padding:13px 0;border-bottom:1px solid var(--line)}
.file-row:last-child{border-bottom:0}
.file-main{flex:1;min-width:0}
.file-path{font-size:14px;word-break:break-word;overflow-wrap:anywhere}
.file-sub{display:flex;gap:7px;align-items:center;color:var(--muted);font-size:12px;margin-top:3px}
.dot{opacity:.55}
.file-actions{display:flex;gap:7px;flex-shrink:0}
.muted{color:var(--muted)}
.small{font-size:13px}
.empty{color:var(--muted);padding:16px 0}
.error-text{color:#ffc0c0;margin:10px 0 0;font-size:14px}
.footer{color:var(--muted);font-size:12px;text-align:center;margin-top:30px;line-height:1.6}
@media (max-width:620px){.wrap{padding:32px 14px 44px}.lookup{flex-direction:column}.lookup .btn{width:100%}.file-row{align-items:flex-start;flex-direction:column}.file-actions{width:100%}.file-actions .btn{flex:1}}
[hidden]{display:none!important}
</style>
</head>
<body>
<main class="wrap">
  <div class="brand">
    <div class="mark">M</div>
    <h1>MEGA Direct</h1>
  </div>
  <p class="sub">Public file and folder links to direct downloads.</p>
  <section class="panel">
    <form id="lookup-form" class="lookup" novalidate>
      <div class="field">
        <label class="sr" for="link">MEGA link</label>
        <input id="link" type="text" placeholder="https://mega.nz/file/...#key" autocomplete="off" spellcheck="false" autocapitalize="off">
      </div>
      <button id="lookup-submit" class="btn primary" type="submit">Get links</button>
    </form>
    <div class="row">
      <button id="paste" class="btn small ghost" type="button">Paste</button>
      <button id="reset" class="btn small ghost" type="button">Reset</button>
    </div>
    <p class="hint">Paste the complete link, including the part after <code>#</code>. Subfolders and files inside folders work too.</p>
    <p id="status" class="status" aria-live="polite"></p>
  </section>
  <div id="result" aria-live="polite" hidden></div>
  <p class="footer">Links are generated on demand and expire after about 20 minutes.</p>
</main>
<script>
(function () {
  "use strict";

  const form = document.getElementById("lookup-form");
  const input = document.getElementById("link");
  const submitButton = document.getElementById("lookup-submit");
  const pasteButton = document.getElementById("paste");
  const resetButton = document.getElementById("reset");
  const status = document.getElementById("status");
  const result = document.getElementById("result");

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatBytes(value) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Number(value) || 0;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    const digits = unit === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;
    return size.toFixed(digits) + " " + units[unit];
  }

  function timeLeft(seconds) {
    const minutes = Math.round((Number(seconds) || 0) / 60);
    return minutes > 0 ? "expires in " + minutes + " min" : "";
  }

  function fallbackCopy(text, done) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } catch (error) {}
    document.body.removeChild(area);
    done();
  }

  function copyText(text, button) {
    const original = button.textContent;
    const done = function () {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = original; }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        fallbackCopy(text, done);
      });
    } else {
      fallbackCopy(text, done);
    }
  }

  function showResult(card) {
    result.replaceChildren(card);
    result.hidden = false;
  }

  function showError(error) {
    const card = make("section", "card error");
    card.appendChild(make("h2", "title", (error && error.code) || "Error"));
    card.appendChild(make("p", "error-text", (error && error.message) || "Something went wrong."));
    if (error && error.code === "missing_key") {
      card.appendChild(make("p", "hint", "Copy the complete MEGA link, including the part after #."));
    }
    showResult(card);
  }

  function addChip(parent, text) {
    if (!text) return;
    parent.appendChild(make("span", "chip", text));
  }

  function fileCard(data) {
    const card = make("section", "card");
    card.appendChild(make("h2", "title", data.name || "File"));
    const meta = make("div", "meta");
    addChip(meta, formatBytes(data.size));
    addChip(meta, data.ext ? data.ext.toUpperCase() : "");
    addChip(meta, timeLeft(data.expires_in));
    card.appendChild(meta);

    const actions = make("div", "actions");
    if (data.url) {
      const open = make("a", "btn primary", "Download");
      open.href = data.url;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      actions.appendChild(open);
      const copy = make("button", "btn", "Copy URL");
      copy.type = "button";
      copy.addEventListener("click", function () { copyText(data.url, copy); });
      actions.appendChild(copy);
    } else {
      actions.appendChild(make("span", "muted small", "Direct URL unavailable."));
    }
    const json = make("button", "btn ghost", "Copy JSON");
    json.type = "button";
    json.addEventListener("click", function () { copyText(JSON.stringify(data, null, 2), json); });
    actions.appendChild(json);
    card.appendChild(actions);
    showResult(card);
  }

  function fileRow(file) {
    const row = make("div", "file-row");
    const main = make("div", "file-main");
    main.appendChild(make("div", "file-path", file.path || file.name || "File"));
    const sub = make("div", "file-sub");
    sub.appendChild(make("span", "", formatBytes(file.size)));
    if (file.ext) {
      sub.appendChild(make("span", "dot", "·"));
      sub.appendChild(make("span", "", file.ext.toUpperCase()));
    }
    main.appendChild(sub);
    row.appendChild(main);

    const actions = make("div", "file-actions");
    if (file.url) {
      const open = make("a", "btn small primary", "Open");
      open.href = file.url;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      actions.appendChild(open);
      const copy = make("button", "btn small", "Copy");
      copy.type = "button";
      copy.addEventListener("click", function () { copyText(file.url, copy); });
      actions.appendChild(copy);
    } else {
      actions.appendChild(make("span", "muted small", "No URL"));
    }
    row.appendChild(actions);
    return row;
  }

  function folderCard(data) {
    const files = Array.isArray(data.files) ? data.files : [];
    const card = make("section", "card");
    card.appendChild(make("h2", "title", data.name || "Folder"));
    const meta = make("div", "meta");
    addChip(meta, files.length + (files.length === 1 ? " file" : " files"));
    addChip(meta, formatBytes(data.size));
    addChip(meta, timeLeft(data.expires_in));
    card.appendChild(meta);

    const urls = files.map(function (file) { return file.url; }).filter(Boolean);
    const actions = make("div", "actions");
    if (urls.length > 0) {
      const copyAll = make("button", "btn primary", "Copy all URLs");
      copyAll.type = "button";
      copyAll.addEventListener("click", function () { copyText(urls.join("\n"), copyAll); });
      actions.appendChild(copyAll);
    }
    const json = make("button", "btn ghost", "Copy JSON");
    json.type = "button";
    json.addEventListener("click", function () { copyText(JSON.stringify(data, null, 2), json); });
    actions.appendChild(json);
    card.appendChild(actions);

    const list = make("div", "files");
    if (files.length === 0) list.appendChild(make("div", "empty", "This folder is empty."));
    for (const file of files) list.appendChild(fileRow(file));
    card.appendChild(list);
    showResult(card);
  }

  function setBusy(busy) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? "Working..." : "Get links";
    status.textContent = busy ? "Contacting MEGA..." : "";
    if (busy) {
      result.hidden = true;
      result.replaceChildren();
    }
  }

  async function resolve(link) {
    const value = String(link || "").trim();
    if (!value) {
      showError({ code: "missing_url", message: "Paste a MEGA link first." });
      input.focus();
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: value }),
      });
      let data;
      try { data = await response.json(); } catch (error) { throw new Error("The worker returned an unreadable response."); }
      if (!data || typeof data !== "object") throw new Error("The worker returned an unexpected response.");
      if (!response.ok || data.error) {
        showError(data.error || { code: "http_" + response.status, message: "The request failed." });
        return;
      }
      if (data.kind === "folder") folderCard(data);
      else if (data.kind === "file") fileCard(data);
      else showError({ code: "bad_response", message: "The worker returned an unexpected response." });
    } catch (error) {
      showError({ code: "network", message: error && error.message ? error.message : "Could not reach the worker." });
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    resolve(input.value);
  });

  pasteButton.addEventListener("click", async function () {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        input.value = text.trim();
        input.focus();
      }
    } catch (error) {
      input.focus();
    }
  });

  resetButton.addEventListener("click", function () {
    input.value = "";
    result.hidden = true;
    result.replaceChildren();
    status.textContent = "";
    input.focus();
  });

  let initial = location.hash.length > 1 ? location.hash.slice(1) : "";
  if (initial && !/^https?:\/\//i.test(initial)) {
    try { initial = decodeURIComponent(initial); } catch (error) {}
  }
  if (initial) {
    input.value = initial;
    resolve(initial);
  } else {
    input.focus();
  }
})();
</script>
</body>
</html>`;function htmlResponse(){return new Response(UI_HTML,{status:200,headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","X-Frame-Options":"DENY","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",Vary:"Accept"}})}async function resolveRequest(request){const started=Date.now();try{const input=await readInput(request);const link=parseMegaLink(input.url,input.key);log("parse",{kind:link.kind,handle:link.handle,keySource:input.keySource,selection:link.selection?link.selection.type:null});let result;if(link.kind==="file"){const key=deriveFileKey(link.key);log("key_decode",{kind:"file",keyChars:link.key.length,aesKeyBytes:key.length});const item=await fetchMegaFile(link.handle);result=buildFileResult(link,key,item)}else{const key=deriveFolderKey(link.key);log("key_decode",{kind:"folder",keyChars:link.key.length,aesKeyBytes:key.length});const nodes=await fetchFolderNodes(link.handle);if(link.selection&&link.selection.type==="file"){result=await buildFolderFileResult(link,key,nodes,link.selection.handle)}else{const startHandle=link.selection&&link.selection.type==="folder"?link.selection.handle:null;result=await buildFolderResult(link,key,nodes,startHandle)}}log("done",{ms:Date.now()-started});return jsonResponse(result)}catch(error){if(error instanceof WorkerError){logError("error",{code:error.code,status:error.status,megaCode:error.megaCode,message:error.message,ms:Date.now()-started});return jsonResponse({error:{code:error.code,message:error.message}},error.status)}logError("error",{code:"internal",message:error instanceof Error?error.message:String(error),ms:Date.now()-started});return jsonResponse({error:{code:"internal",message:"Something broke on our side."}},500)}}var main_default={async fetch(request,env){if(request.method==="OPTIONS"){return optionsResponse()}const requestUrl=new URL(request.url);if(request.method==="GET"&&requestUrl.pathname==="/favicon.ico"){return new Response(null,{status:204,headers:{"Cache-Control":"public, max-age=86400"}})}if(requestUrl.pathname==="/bot/resolve"){if(request.method!=="POST"){return jsonResponse({error:{code:"method_not_allowed",message:"Use POST."}},405)}const auth=checkWorkerKey(request,env);if(!auth.ok){logError("bot_auth",{code:auth.code,status:auth.status});return jsonResponse({error:{code:auth.code,message:auth.message}},auth.status)}log("bot_resolve",{});return resolveRequest(request)}if(request.method==="GET"&&(requestUrl.pathname==="/ui"||requestUrl.pathname==="/"&&!requestUrl.searchParams.has("url")&&!requestUrl.searchParams.has("link")&&!requestUrl.searchParams.has("key")&&!requestUrl.searchParams.has("k")&&(request.headers.get("accept")||"").includes("text/html"))){log("ui",{path:requestUrl.pathname});return htmlResponse()}log("request",{method:request.method});return resolveRequest(request)}};export{main_default as default};
